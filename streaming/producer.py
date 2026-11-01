"""Transaction producer = replay of the existing `transactions` table onto a Redis Stream.

Stand-in for a real transaction source (UPI switch / webhook / Kafka bridge). Replace this one
process with your real source; it only has to XADD events shaped like `encode_event()` produces.

Demo sampling: with probability PRODUCER_FRAUD_BOOST the next event is a not-yet-replayed
*real labelled fraud* row (otherwise the next sequential row). The dataset is 0.17% fraud, so
pure sequential replay would show a fraud alert only every ~10 minutes. The boost is published
in the heartbeat so the dashboard can disclose that the live fraud share is inflated.
"""
import json
import logging
import os
import random
import signal
import time

from core import db
from core.config import get_settings
from core.logging_config import setup_logging
from core.redis_client import get_sync_redis
from core.repository import RAW_SELECT
from core.model_store import ModelStore
from streaming.common import encode_event, heartbeat

log = logging.getLogger("producer")
CURSOR_KEY = "producer:cursor"
FRAUD_SENT_KEY = "producer:fraud_sent"
_stop = False


def _sig(*_):
    global _stop
    _stop = True


def next_sequential(cursor: int) -> dict | None:
    return db.query_one(f"SELECT {RAW_SELECT} FROM transactions WHERE transaction_id > %s "
                        "ORDER BY transaction_id LIMIT 1", (cursor,))


def next_fraud(r, cutoff: float | None = None) -> dict | None:
    sent = [int(x) for x in r.smembers(FRAUD_SENT_KEY)]
    return db.query_one(f"SELECT {RAW_SELECT} FROM transactions WHERE actual_class = 1 AND transaction_time > %s "
                        "AND NOT (transaction_id = ANY(%s)) ORDER BY random() LIMIT 1", (cutoff if cutoff is not None else -1, sent))


def heldout_cutoff() -> float | None:
    """Training-period boundary of the active model (None if unknown)."""
    try:
        return ModelStore().metadata()["data"].get("train_time_max")
    except Exception:
        return None


def run(max_events: int | None = None) -> int:
    s = get_settings()
    r = get_sync_redis()
    boost = float(os.getenv("PRODUCER_FRAUD_BOOST", "0.03"))
    mode = os.getenv("PRODUCER_REPLAY_FROM", "heldout").lower()          # heldout | all
    cutoff = heldout_cutoff() if mode == "heldout" else None
    if mode == "heldout" and cutoff is None:
        log.warning("active model has no train_time_max; replaying all rows (live metrics will include training data)")
    if cutoff is not None:
        first = db.query_one("SELECT min(transaction_id) AS i FROM transactions WHERE transaction_time > %s", (cutoff,))["i"]
        if first is not None and int(r.get(CURSOR_KEY) or 0) < first - 1:
            r.set(CURSOR_KEY, first - 1)                                   # skip the training period
    name = s.consumer_name
    sent = 0
    log.info("producer started", extra={"min_ms": s.producer_min_delay_ms, "max_ms": s.producer_max_delay_ms,
                                         "fraud_boost": boost, "replay_from": mode if cutoff is not None else "all"})
    while not _stop and (max_events is None or sent < max_events):
        cursor = int(r.get(CURSOR_KEY) or 0)
        row, boosted = None, False
        if boost > 0 and random.random() < boost:
            row = next_fraud(r, cutoff)
            boosted = row is not None
        if row is None:
            row = next_sequential(cursor)
        if row is None:
            heartbeat(r, "producer", name, state="completed", sent=sent, fraud_boost=boost)
            log.info("replay finished - all transactions were produced")
            time.sleep(5)
            continue
        r.xadd(s.stream_name, encode_event(row), maxlen=s.stream_maxlen, approximate=True)
        if boosted:
            r.sadd(FRAUD_SENT_KEY, row["transaction_id"])
        else:
            r.set(CURSOR_KEY, row["transaction_id"])
        sent += 1
        heartbeat(r, "producer", name, state="running", sent=sent, fraud_boost=boost, replay_from=(mode if cutoff is not None else "all"),
                  min_delay_ms=s.producer_min_delay_ms, max_delay_ms=s.producer_max_delay_ms)
        time.sleep(random.uniform(s.producer_min_delay_ms, s.producer_max_delay_ms) / 1000)
    return sent


if __name__ == "__main__":
    setup_logging(get_settings().log_level)
    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)
    run()
