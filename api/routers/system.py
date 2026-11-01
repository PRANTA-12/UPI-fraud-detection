import time

from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool

from api.ws import manager
from core import db
from core.config import get_settings
from core.metrics import api_latency
from core.model_store import get_store
from core.security import require_role
from streaming.common import read_heartbeats

router = APIRouter(prefix="/system", tags=["system health"], dependencies=[Depends(require_role("viewer"))])


async def stream_snapshot(r) -> dict:
    s = get_settings()
    out = {"stream": s.stream_name, "dlq_stream": s.dlq_stream_name, "length": None, "groups": [],
           "dlq_length": None, "dlq_recent": [], "redis": {"status": "down", "latency_ms": None}}
    try:
        t0 = time.perf_counter()
        await r.ping()
        out["redis"] = {"status": "up", "latency_ms": round((time.perf_counter() - t0) * 1000, 2)}
        out["length"] = await r.xlen(s.stream_name)
        out["dlq_length"] = await r.xlen(s.dlq_stream_name)
        try:
            for g in await r.xinfo_groups(s.stream_name):
                out["groups"].append({"name": g.get("name"), "consumers": g.get("consumers"),
                                      "pending": g.get("pending"), "lag": g.get("lag"),
                                      "last_delivered_id": g.get("last-delivered-id"),
                                      "last-delivered-id": g.get("last-delivered-id")})
        except Exception:
            pass                                     # stream/group not created yet
        recent = await r.xrevrange(s.dlq_stream_name, count=5)
        out["dlq_recent"] = [{"id": i, "original_id": f.get("original_id"), "error": f.get("error"),
                              "deliveries": f.get("deliveries"), "failed_at": f.get("failed_at")} for i, f in recent]
    except Exception:
        pass
    return out


def _status(ok: bool, degraded: bool = False) -> str:
    return "operational" if ok and not degraded else "degraded" if ok else "down"


@router.get("/health")
async def system_health(request: Request):
    s = get_settings()
    t0 = time.perf_counter()
    db_ok = await run_in_threadpool(db.ping)
    db_ms = round((time.perf_counter() - t0) * 1000, 2)
    snap = await stream_snapshot(request.app.state.redis)
    redis_ok = snap["redis"]["status"] == "up"
    consumers = await run_in_threadpool(read_heartbeats, request.app.state.sync_redis, "consumer") if redis_ok else []
    producers = await run_in_threadpool(read_heartbeats, request.app.state.sync_redis, "producer") if redis_ok else []
    live_consumers = [c for c in consumers if c["age_s"] < 15]
    group = next((g for g in snap["groups"] if g["name"] == s.consumer_group), None)
    perf = await run_in_threadpool(db.query_one, """
        SELECT count(*) FILTER (WHERE processed_at > now() - interval '60 seconds') AS last_60s,
               count(*) FILTER (WHERE status='completed') AS total,
               count(*) FILTER (WHERE source='stream') AS stream_total
        FROM fraud_predictions""") if db_ok else {"last_60s": 0, "total": 0, "stream_total": 0}
    try:
        model = get_store().active_version()
    except Exception:
        model = None
    lag = (group or {}).get("lag")
    components = {
        "api": {"status": "operational", "latency": api_latency.snapshot()},
        "postgresql": {"status": _status(db_ok), "latency_ms": db_ms},
        "redis": {**snap["redis"], "status": _status(redis_ok)},
        "consumers": {"status": _status(bool(live_consumers), degraded=bool(lag and lag > 1000)) if redis_ok else "down",
                      "live": len(live_consumers), "instances": consumers,
                      "note": "A consumer is live if its heartbeat is < 15 s old."},
        "producer": {"status": ("operational" if any(p["age_s"] < 15 for p in producers) else "idle") if redis_ok else "down",
                     "instances": producers},
        "dead_letter_queue": {"status": "degraded" if (snap["dlq_length"] or 0) > 0 else "operational",
                              "size": snap["dlq_length"], "recent": snap["dlq_recent"]},
        "websocket": {"status": "operational", "connections": len(manager.clients),
                      "messages_sent": manager.messages_sent},
        "model": {"status": "operational" if model else "down", "active_version": model},
    }
    statuses = [c["status"] for k, c in components.items() if k != "producer"]
    overall = "down" if "down" in statuses else "degraded" if "degraded" in statuses else "operational"
    return {"overall": overall, "checked_at": time.time(), "components": components,
            "stream": {"name": snap["stream"], "length": snap["length"], "groups": snap["groups"]},
            "throughput": {"predictions_last_60s": perf["last_60s"], "tps_60s": perf["last_60s"] / 60.0,
                           "total_predictions": perf["total"], "stream_predictions": perf["stream_total"]},
            "disclaimer": "Only measured values are shown. CPU/RAM are not reported by this service."}
