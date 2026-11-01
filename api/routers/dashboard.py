from typing import Literal

from fastapi import APIRouter, Depends, Query

from api.deps import DateRange, active_model_info, current_settings, held_out_block, held_out_sql
from core import db
from core.cache import ttl_cache
from core.platform_settings import PlatformSettings
from core.risk import risk_case_sql
from core.security import require_role

router = APIRouter(prefix="/dashboard", tags=["dashboard"], dependencies=[Depends(require_role("viewer"))])

BASE = "FROM latest_predictions lp JOIN transactions t USING (transaction_id)"


@ttl_cache(2)
def _kpis(high_min: float, df, dt, mv, active, cutoff):
    where, params = [], []
    if df:
        where.append("lp.processed_at >= %s"); params.append(df)
    if dt:
        where.append("lp.processed_at <= %s"); params.append(dt)
    if mv:
        where.append("lp.model_version = %s"); params.append(mv)
    ho_sql, ho_params = held_out_sql(active, cutoff)
    w = ("WHERE " + " AND ".join(where)) if where else ""
    c = db.query_one(f"""
        SELECT count(*) AS processed,
               count(*) FILTER (WHERE lp.predicted_class = 0) AS pred_legit,
               count(*) FILTER (WHERE lp.predicted_class = 1) AS pred_flagged,
               count(*) FILTER (WHERE lp.fraud_probability >= %s) AS high_risk,
               count(*) FILTER (WHERE t.actual_class = 1) AS actual_fraud,
               count(*) FILTER (WHERE lp.predicted_class = 1 AND t.actual_class = 1) AS tp,
               count(*) FILTER (WHERE lp.predicted_class = 1 AND t.actual_class = 0) AS fp,
               count(*) FILTER (WHERE lp.predicted_class = 0 AND t.actual_class = 1) AS fn,
               COALESCE(sum(t.amount), 0)::float8 AS total_amount,
               COALESCE(sum(t.amount) FILTER (WHERE lp.predicted_class = 1), 0)::float8 AS flagged_amount,
               {ho_sql}
        {BASE} {w}""", [high_min, *ho_params, *params])
    perf = db.query_one("""
        SELECT count(*) FILTER (WHERE processed_at > now() - interval '60 seconds') AS last_60s,
               avg(latency_ms) FILTER (WHERE source='stream' AND processed_at > now() - interval '15 minutes') AS avg_latency,
               percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms)
                   FILTER (WHERE source='stream' AND processed_at > now() - interval '15 minutes') AS p95_latency,
               avg(inference_ms) FILTER (WHERE source='stream' AND processed_at > now() - interval '15 minutes') AS avg_inference
        FROM fraud_predictions WHERE processed_at > now() - interval '15 minutes' AND status='completed'""")
    in_db = db.query_one("SELECT count(*) AS n FROM transactions")["n"]
    tp, fp, fn = c["tp"], c["fp"], c["fn"]
    return {
        "scope": {"definition": "Latest prediction per transaction", "time_axis": "prediction processing time",
                  "date_from": df, "date_to": dt, "transactions_in_database": in_db},
        "predicted": {"processed": c["processed"], "legitimate": c["pred_legit"], "flagged": c["pred_flagged"],
                      "high_risk": c["high_risk"],
                      "flagged_rate": (c["pred_flagged"] / c["processed"]) if c["processed"] else None},
        "ground_truth": {"note": "Actual labels come from the replayed dataset (in production labels arrive late). "
                                 "These figures include transactions the model was trained on - use `held_out` for an honest estimate.",
                         "held_out": held_out_block(c, active, cutoff),
                         "actual_fraud_processed": c["actual_fraud"], "caught": tp, "missed": fn,
                         "false_alarms": fp,
                         "detection_rate": (tp / c["actual_fraud"]) if c["actual_fraud"] else None,
                         "precision": (tp / (tp + fp)) if (tp + fp) else None},
        "amounts": {"total": c["total_amount"], "flagged": c["flagged_amount"], "unit": "dataset currency units"},
        "performance": {"throughput_tps_60s": (perf["last_60s"] or 0) / 60.0,
                        "avg_latency_ms_15m": perf["avg_latency"], "p95_latency_ms_15m": perf["p95_latency"],
                        "avg_inference_ms_15m": perf["avg_inference"],
                        "latency_definition": "stream enqueue -> prediction ready (before DB commit)"},
    }


@router.get("/kpis")
def kpis(dr: DateRange = Depends(), ps: PlatformSettings = Depends(current_settings)):
    active, cutoff = active_model_info()
    return _kpis(ps.risk_high_min, dr.date_from, dr.date_to, dr.model_version, active, cutoff)


@router.get("/trends")
def trends(bucket: Literal["minute", "hour", "day"] = "minute",
           window_hours: int = Query(2, ge=1, le=24 * 30)):
    rows = db.query_all("""
        SELECT date_trunc(%s, p.processed_at) AS bucket, count(*) AS events,
               count(*) FILTER (WHERE p.predicted_class = 1) AS flagged,
               count(*) FILTER (WHERE t.actual_class = 1) AS actual_fraud,
               COALESCE(sum(t.amount), 0)::float8 AS amount,
               avg(p.latency_ms) FILTER (WHERE p.source = 'stream') AS avg_latency_ms
        FROM fraud_predictions p JOIN transactions t USING (transaction_id)
        WHERE p.status = 'completed' AND p.processed_at >= now() - make_interval(hours => %s)
        GROUP BY 1 ORDER BY 1""", (bucket, window_hours))
    return {"bucket": bucket, "window_hours": window_hours, "time_axis": "prediction processing time",
            "points": rows}


@router.get("/risk-distribution")
def risk_distribution(dr: DateRange = Depends(), ps: PlatformSettings = Depends(current_settings)):
    case, cparams = risk_case_sql("lp.fraud_probability", ps.risk_low_max, ps.risk_high_min)
    where, wparams = dr.where()
    w = ("WHERE " + " AND ".join(where)) if where else ""
    rows = db.query_all(f"SELECT {case} AS risk, count(*) AS n FROM latest_predictions lp {w} GROUP BY 1",
                        [*cparams, *wparams])
    got = {r["risk"]: r["n"] for r in rows}
    return {"bands": {"low_max": ps.risk_low_max, "high_min": ps.risk_high_min},
            "distribution": [{"risk": k, "count": got.get(k, 0)} for k in ("Low", "Medium", "High")]}


@router.get("/recent-suspicious")
def recent_suspicious(limit: int = Query(10, ge=1, le=50), ps: PlatformSettings = Depends(current_settings)):
    case, cparams = risk_case_sql("lp.fraud_probability", ps.risk_low_max, ps.risk_high_min)
    rows = db.query_all(f"""
        SELECT lp.transaction_id, t.amount::float8 AS amount, lp.fraud_probability, {case} AS risk_level,
               lp.predicted_class, t.actual_class, lp.model_version, lp.processed_at
        {BASE} WHERE lp.predicted_class = 1 OR lp.fraud_probability >= %s
        ORDER BY lp.processed_at DESC LIMIT %s""", [*cparams, ps.risk_high_min, limit])
    return {"items": rows}
