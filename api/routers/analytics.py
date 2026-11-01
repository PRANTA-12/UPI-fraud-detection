from fastapi import APIRouter, Depends

from api.deps import DateRange, active_model_info, current_settings, held_out_block, held_out_sql
from core import db
from core.platform_settings import PlatformSettings
from core.security import require_role

router = APIRouter(prefix="/analytics", tags=["analytics"], dependencies=[Depends(require_role("viewer"))])

FROM = "FROM latest_predictions lp JOIN transactions t USING (transaction_id)"
AMOUNT_EDGES = [1, 10, 50, 100, 500, 1000]
AMOUNT_LABELS = ["< 1", "1 - 10", "10 - 50", "50 - 100", "100 - 500", "500 - 1k", "1k +"]
AMOUNT_CASE = ("CASE " + " ".join(f"WHEN t.amount < {e} THEN {i}" for i, e in enumerate(AMOUNT_EDGES))
               + f" ELSE {len(AMOUNT_EDGES)} END")


def _w(dr: DateRange, extra: list[str] | None = None, extra_params: list | None = None):
    where, params = dr.where()
    where += extra or []
    params += extra_params or []
    return (("WHERE " + " AND ".join(where)) if where else ""), params


@router.get("/summary")
def summary(dr: DateRange = Depends(), ps: PlatformSettings = Depends(current_settings)):
    w, p = _w(dr)
    active, cutoff = active_model_info()
    ho_sql, ho_params = held_out_sql(active, cutoff)
    r = db.query_one(f"""
        SELECT {ho_sql},
               count(*) AS n,
               count(*) FILTER (WHERE t.actual_class = 1) AS actual_fraud,
               count(*) FILTER (WHERE lp.predicted_class = 1) AS flagged,
               count(*) FILTER (WHERE lp.predicted_class = 1 AND t.actual_class = 1) AS tp,
               count(*) FILTER (WHERE lp.predicted_class = 1 AND t.actual_class = 0) AS fp,
               count(*) FILTER (WHERE lp.predicted_class = 0 AND t.actual_class = 1) AS fn,
               count(*) FILTER (WHERE lp.predicted_class = 0 AND t.actual_class = 0) AS tn,
               count(*) FILTER (WHERE lp.fraud_probability >= %s) AS high_risk,
               avg(lp.fraud_probability) AS avg_probability
        {FROM} {w}""", [*ho_params, ps.risk_high_min, *p])
    tp, fp, fn = r["tp"], r["fp"], r["fn"]
    prec = tp / (tp + fp) if tp + fp else None
    rec = tp / (tp + fn) if tp + fn else None
    f1 = 2 * prec * rec / (prec + rec) if prec and rec else None
    return {"processed": r["n"], "actual_fraud": r["actual_fraud"], "predicted_flagged": r["flagged"],
            "high_risk": r["high_risk"], "avg_probability": r["avg_probability"],
            "confusion_matrix": {"tp": tp, "fp": fp, "fn": fn, "tn": r["tn"]},
            "precision": prec, "recall": rec, "f1": f1, "held_out": held_out_block(r, active, cutoff),
            "note": "Live confusion matrix over processed transactions (replayed labels). Held-out test-set "
                    "metrics are on the AI Model page."}


@router.get("/hourly")
def hourly(dr: DateRange = Depends()):
    w, p = _w(dr)
    rows = db.query_all(f"""
        SELECT mod(floor(t.transaction_time / 3600)::int, 24) AS hour, count(*) AS transactions,
               count(*) FILTER (WHERE lp.predicted_class = 1) AS flagged,
               count(*) FILTER (WHERE t.actual_class = 1) AS actual_fraud
        {FROM} {w} GROUP BY 1 ORDER BY 1""", p)
    got = {r["hour"]: r for r in rows}
    return {"note": "Hour = hours since the first transaction in the source dataset, modulo 24 (the dataset has "
                    "no wall-clock timestamps).",
            "points": [got.get(h, {"hour": h, "transactions": 0, "flagged": 0, "actual_fraud": 0}) for h in range(24)]}


@router.get("/amount-distribution")
def amount_distribution(dr: DateRange = Depends()):
    w, p = _w(dr)
    rows = db.query_all(f"""
        SELECT {AMOUNT_CASE} AS b, count(*) AS transactions,
               count(*) FILTER (WHERE lp.predicted_class = 1) AS flagged,
               count(*) FILTER (WHERE t.actual_class = 1) AS actual_fraud
        {FROM} {w} GROUP BY 1 ORDER BY 1""", p)
    got = {r["b"]: r for r in rows}
    return {"unit": "dataset currency units",
            "buckets": [{"label": AMOUNT_LABELS[i], **{k: got.get(i, {}).get(k, 0)
                                                       for k in ("transactions", "flagged", "actual_fraud")}}
                        for i in range(len(AMOUNT_LABELS))]}


@router.get("/probability-distribution")
def probability_distribution(dr: DateRange = Depends()):
    w, p = _w(dr)
    rows = db.query_all(f"""
        SELECT LEAST(floor(lp.fraud_probability * 20), 19)::int AS b, count(*) AS n,
               count(*) FILTER (WHERE t.actual_class = 1) AS actual_fraud
        {FROM} {w} GROUP BY 1 ORDER BY 1""", p)
    got = {r["b"]: r for r in rows}
    return {"bins": [{"from": i / 20, "to": (i + 1) / 20, "count": got.get(i, {}).get("n", 0),
                      "actual_fraud": got.get(i, {}).get("actual_fraud", 0)} for i in range(20)]}


@router.get("/high-risk-patterns")
def high_risk_patterns(dr: DateRange = Depends(), ps: PlatformSettings = Depends(current_settings)):
    w, p = _w(dr, ["lp.fraud_probability >= %s"], [ps.risk_high_min])
    by_amount = db.query_all(f"SELECT {AMOUNT_CASE} AS b, count(*) AS n {FROM} {w} GROUP BY 1 ORDER BY 1", p)
    by_hour = db.query_all(f"SELECT mod(floor(t.transaction_time/3600)::int, 24) AS hour, count(*) AS n "
                           f"{FROM} {w} GROUP BY 1 ORDER BY 1", p)
    stats = db.query_one(f"SELECT count(*) AS n, avg(t.amount)::float8 AS avg_amount, "
                         f"avg(lp.fraud_probability) AS avg_prob {FROM} {w}", p)
    ga = {r["b"]: r["n"] for r in by_amount}
    return {"high_risk_threshold": ps.risk_high_min, "count": stats["n"], "avg_amount": stats["avg_amount"],
            "by_amount": [{"label": AMOUNT_LABELS[i], "count": ga.get(i, 0)} for i in range(len(AMOUNT_LABELS))],
            "by_hour": by_hour}
