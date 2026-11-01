"""Original endpoints. Paths, request and response fields are preserved (new fields are additive)."""
import time
from datetime import datetime, timezone

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Request

from api.deps import audit
from api.schemas import PredictRequest, PredictResponse
from core import db
from core.config import get_settings
from core.model_store import get_store
from core.platform_settings import load_settings
from core.ratelimit import rate_limit
from core.repository import fetch_transaction, insert_prediction
from core.risk import risk_level
from core.security import legacy_guard

router = APIRouter(tags=["core (original endpoints)"])


@router.get("/")
def root():
    s = get_settings()
    try:
        version = get_store().active_version()
    except Exception:
        version = None
    return {"message": "UPI Fraud Detection API is running", "live_feed": "/app/#/live", "websocket": "/ws/live",
            "name": "UPI SENTINEL", "description": "AI-powered real-time fraud detection and risk intelligence",
            "version": "2.0.0", "model_version": version, "docs": "/docs", "dashboard": "/app/",
            "dataset_notice": "Prototype trained on the public Credit Card Fraud Detection dataset "
                              "(anonymised features); it is not native UPI data.",
            "auth_required": s.auth_required}


@router.get("/health")
def health():
    """Original contract: 200 {"status":"healthy",...} or 503 when the database is unreachable."""
    if not db.ping():
        raise HTTPException(503, "Database connection unavailable")
    try:
        version = get_store().active_version()
    except Exception:
        version = None
    return {"status": "healthy", "model": "XGBoost", "database": "PostgreSQL", "database_connection": "ok",
            "model_version": version}


@router.post("/predict", response_model=PredictResponse,
             dependencies=[Depends(legacy_guard("analyst")), Depends(rate_limit(60, 60, "predict"))])
async def predict(body: PredictRequest, request: Request):
    # sync DB/model work runs in the threadpool so the event loop stays free
    from starlette.concurrency import run_in_threadpool
    result = await run_in_threadpool(_predict_sync, body.transaction_id)
    audit_user = None
    await run_in_threadpool(audit, request, audit_user, "predict", {"transaction_id": body.transaction_id})
    r = getattr(request.app.state, "redis", None)
    if r is not None:
        import json
        try:
            await r.publish(get_settings().alert_channel, json.dumps({**result["event"]}, default=str))
        except Exception:
            pass
    return result["response"]


def _predict_sync(txn_id: int) -> dict:
    t0 = time.perf_counter()
    raw = fetch_transaction(txn_id)
    if raw is None:
        raise HTTPException(404, f"Transaction ID {txn_id} not found")
    bundle = get_store().get()
    proba = float(bundle.predict_proba(pd.DataFrame([raw]))[0])
    inference_ms = (time.perf_counter() - t0) * 1000
    pred = int(proba >= bundle.threshold)
    ps = load_settings()
    risk = risk_level(proba, ps.risk_low_max, ps.risk_high_min)
    with db.get_conn() as conn, conn.cursor() as cur:
        saved = insert_prediction(cur, transaction_id=txn_id, probability=proba, predicted_class=pred,
                                  model_name="XGBoost", model_version=bundle.version, threshold=bundle.threshold,
                                  risk_level=risk, source="api", enqueued_at=None, inference_ms=inference_ms,
                                  latency_ms=inference_ms)
    resp = {"prediction_id": saved["prediction_id"], "transaction_id": txn_id, "prediction": pred,
            "result": "Fraud" if pred else "Legitimate", "fraud_probability": proba, "risk_level": risk,
            "threshold": bundle.threshold, "model": "XGBoost", "model_version": bundle.version,
            "latency_ms": round(inference_ms, 3)}
    event = {"type": "prediction", **resp, "amount": raw["amount"], "predicted_class": pred, "source": "api",
             "status": "completed", "processed_at": saved["processed_at"].isoformat(),
             "alert": bool(pred), "actual_class": raw["actual_class"], "inference_ms": round(inference_ms, 3)}
    return {"response": resp, "event": event}


@router.get("/stream/status", dependencies=[Depends(legacy_guard("viewer"))])
async def stream_status(request: Request):
    """Original keys (stream, pending_length, consumer_groups) kept; new keys added."""
    from api.routers.system import stream_snapshot
    snap = await stream_snapshot(request.app.state.redis)
    if snap["redis"]["status"] != "up":
        raise HTTPException(503, "Redis unavailable")
    return {"stream": snap["stream"], "pending_length": snap["length"], "consumer_groups": snap["groups"],
            "length": snap["length"], "groups": snap["groups"], "dlq_length": snap["dlq_length"], "redis": snap["redis"]}
