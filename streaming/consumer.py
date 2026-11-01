"""Real-time fraud scorer.

Guarantees
  * consumer group => N consumers share the stream, each message is delivered to one of them
  * idempotent: unique idempotency_key = "<transaction_id>:<model_version>" (replays/redeliveries
    cannot create duplicate predictions or duplicate alerts)
  * at-least-once: a message is XACKed only after the prediction is committed
  * bounded retries: failures stay pending, are re-claimed after RETRY_IDLE_MS, and after
    MAX_RETRIES deliveries are moved to the dead-letter stream (poison messages go there at once)
  * measured latency: enqueue -> prediction-ready (latency_ms) and pure model time (inference_ms)
"""
import json
import logging
import signal
import time
from datetime import datetime, timezone

import pandas as pd
import redis

from core import db
from core.config import Settings, get_settings
from core.features import RAW_COLUMNS
from core.logging_config import setup_logging
from core.model_store import ModelStore
from core.platform_settings import load_settings
from core.redis_client import get_sync_redis
from core.repository import ensure_transaction, insert_prediction
from core.risk import risk_level
from streaming.common import heartbeat

log = logging.getLogger("consumer")
SOURCE = "stream"
MODEL_NAME = "XGBoost-Streaming"      # kept from the original project so old queries/filters still work


class PoisonMessage(Exception):
    """Message can never succeed (bad JSON / missing fields) - dead-letter immediately."""


class Consumer:
    def __init__(self, r: redis.Redis, store: ModelStore | None = None, settings: Settings | None = None):
        self.r = r
        self.s = settings or get_settings()
        self.store = store or ModelStore()
        self.processed = self.failed = self.dead = self.duplicates = 0
        self._stop = False
        self._last_reclaim = 0.0
        self._last_model_check = 0.0
        self.bundle = self.store.get()

    # ---- setup / helpers --------------------------------------------------------------------
    def ensure_group(self) -> None:
        try:
            self.r.xgroup_create(self.s.stream_name, self.s.consumer_group, id="0", mkstream=True)
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    def stop(self, *_):
        self._stop = True

    def _refresh_model(self) -> None:
        if time.monotonic() - self._last_model_check < 30:
            return
        self._last_model_check = time.monotonic()
        try:
            active = self.store.active_version()
            if active != self.bundle.version:
                self.bundle = self.store.get(active)
                log.info("switched model", extra={"version": active})
        except Exception as e:
            log.warning("model refresh failed", extra={"error": str(e)})

    @staticmethod
    def _parse(fields: dict, msg_id: str) -> tuple[dict, datetime]:
        try:
            payload = json.loads(fields["data"])
            missing = [c for c in ["transaction_id", *RAW_COLUMNS] if payload.get(c) is None]
            if missing:
                raise PoisonMessage(f"missing fields: {missing}")
            int(payload["transaction_id"])
        except (KeyError, json.JSONDecodeError, TypeError, ValueError) as e:
            raise PoisonMessage(f"unparseable message: {e}") from e
        ms = int(fields.get("enqueued_at_ms") or msg_id.split("-")[0])
        return payload, datetime.fromtimestamp(ms / 1000, tz=timezone.utc)

    # ---- core --------------------------------------------------------------------------------
    def process_one(self, msg_id: str, fields: dict) -> str:
        """Returns 'ok' | 'duplicate'. Raises PoisonMessage or a transient exception."""
        payload, enqueued_at = self._parse(fields, msg_id)
        tid = int(payload["transaction_id"])
        t0 = time.perf_counter()
        proba = float(self.bundle.predict_proba(pd.DataFrame([payload]))[0])
        inference_ms = (time.perf_counter() - t0) * 1000
        pred = int(proba >= self.bundle.threshold)
        ps = load_settings()
        risk = risk_level(proba, ps.risk_low_max, ps.risk_high_min)
        latency_ms = (datetime.now(timezone.utc) - enqueued_at).total_seconds() * 1000
        with db.get_conn() as conn, conn.cursor() as cur:
            ensure_transaction(cur, payload)
            saved = insert_prediction(
                cur, transaction_id=tid, probability=proba, predicted_class=pred, model_name=MODEL_NAME,
                model_version=self.bundle.version, threshold=self.bundle.threshold, risk_level=risk,
                source=SOURCE, enqueued_at=enqueued_at, inference_ms=inference_ms, latency_ms=latency_ms,
                idempotency_key=f"{tid}:{self.bundle.version}")
        if saved is None:
            return "duplicate"
        event = {"type": "prediction", "prediction_id": saved["prediction_id"], "transaction_id": tid,
                 "amount": float(payload["amount"]), "fraud_probability": proba, "predicted_class": pred,
                 "result": "Fraud" if pred else "Legitimate", "risk_level": risk,
                 "threshold": self.bundle.threshold, "model_version": self.bundle.version,
                 "model_name": MODEL_NAME, "model": MODEL_NAME, "prediction": pred, "source": SOURCE, "status": "completed",
                 "processed_at": saved["processed_at"].isoformat(), "latency_ms": round(latency_ms, 2),
                 "inference_ms": round(inference_ms, 3), "alert": bool(pred),
                 "actual_class": payload.get("actual_class")}     # label exists only for replayed history
        self.r.publish(self.s.alert_channel, json.dumps(event))
        return "ok"

    def dead_letter(self, msg_id: str, fields: dict, error: str, deliveries: int) -> None:
        self.r.xadd(self.s.dlq_stream_name, {
            "original_id": msg_id, "data": fields.get("data", ""), "error": error[:500],
            "deliveries": str(deliveries), "failed_at": datetime.now(timezone.utc).isoformat()},
            maxlen=10_000, approximate=True)
        self.r.xack(self.s.stream_name, self.s.consumer_group, msg_id)
        self.dead += 1
        log.error("dead-lettered", extra={"msg_id": msg_id, "error": error[:200], "deliveries": deliveries})

    def handle(self, msg_id: str, fields: dict, deliveries: int = 1) -> None:
        try:
            for attempt, delay in enumerate((0.0, 0.2, 0.5)):          # short in-process retry for blips
                try:
                    if delay:
                        time.sleep(delay)
                    outcome = self.process_one(msg_id, fields)
                    break
                except PoisonMessage:
                    raise
                except Exception as e:
                    if attempt == 2:
                        raise
                    log.warning("transient failure, retrying", extra={"msg_id": msg_id, "error": str(e)})
            self.r.xack(self.s.stream_name, self.s.consumer_group, msg_id)
            if outcome == "duplicate":
                self.duplicates += 1
            else:
                self.processed += 1
        except PoisonMessage as e:
            self.failed += 1
            self.dead_letter(msg_id, fields, str(e), deliveries)
        except Exception as e:
            self.failed += 1
            if deliveries >= self.s.max_retries:
                self.dead_letter(msg_id, fields, f"max retries exceeded: {e}", deliveries)
            else:
                log.error("processing failed; will be retried", extra={"msg_id": msg_id, "error": str(e),
                                                                       "deliveries": deliveries})

    def reclaim_stale(self) -> int:
        """Re-process messages stuck pending (crashed consumer or failed attempts)."""
        n = 0
        res = self.r.xautoclaim(self.s.stream_name, self.s.consumer_group, self.s.consumer_name,
                                min_idle_time=self.s.retry_idle_ms, start_id="0-0", count=20)
        for msg_id, fields in (res[1] if res else []):
            if not fields:
                self.r.xack(self.s.stream_name, self.s.consumer_group, msg_id)   # trimmed from stream
                continue
            info = self.r.xpending_range(self.s.stream_name, self.s.consumer_group, msg_id, msg_id, 1)
            deliveries = int(info[0]["times_delivered"]) if info else 1
            self.handle(msg_id, fields, deliveries)
            n += 1
        return n

    def step(self, block_ms: int = 2000, count: int = 20) -> int:
        self._refresh_model()
        if time.monotonic() - self._last_reclaim > 10:
            self._last_reclaim = time.monotonic()
            self.reclaim_stale()
        res = self.r.xreadgroup(self.s.consumer_group, self.s.consumer_name,
                                {self.s.stream_name: ">"}, count=count, block=block_ms)
        n = 0
        for _stream, messages in res or []:
            for msg_id, fields in messages:
                self.handle(msg_id, fields)
                n += 1
        heartbeat(self.r, "consumer", self.s.consumer_name, processed=self.processed, failed=self.failed,
                  dead_lettered=self.dead, duplicates=self.duplicates, model_version=self.bundle.version)
        return n

    def run(self) -> None:
        self.ensure_group()
        log.info("consumer started", extra={"consumer": self.s.consumer_name, "group": self.s.consumer_group,
                                             "model": self.bundle.version})
        while not self._stop:
            try:
                self.step()
            except redis.ConnectionError as e:
                log.error("redis unavailable, backing off", extra={"error": str(e)})
                time.sleep(3)
            except redis.ResponseError as e:
                if "NOGROUP" in str(e):
                    self.ensure_group()
                else:
                    raise


if __name__ == "__main__":
    setup_logging(get_settings().log_level)
    c = Consumer(get_sync_redis())
    signal.signal(signal.SIGTERM, c.stop)
    signal.signal(signal.SIGINT, c.stop)
    c.run()
