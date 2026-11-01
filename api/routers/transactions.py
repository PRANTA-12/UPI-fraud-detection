import math
from typing import Literal

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.concurrency import run_in_threadpool

from api.deps import DateRange, PageParams, current_settings
from api.schemas import Page, TransactionRow
from core import db
from core.features import V_COLUMNS
from core.model_store import get_store
from core.platform_settings import PlatformSettings
from core.repository import fetch_transaction
from core.risk import risk_case_sql, risk_level
from core.security import require_role

router = APIRouter(prefix="/transactions", tags=["investigation"], dependencies=[Depends(require_role("viewer"))])

SORT_COLUMNS = {"processed_at": "lp.processed_at", "fraud_probability": "lp.fraud_probability",
                "amount": "t.amount", "transaction_id": "lp.transaction_id", "latency_ms": "lp.latency_ms"}


@router.get("", response_model=Page[TransactionRow])
def list_transactions(
        pg: PageParams = Depends(), dr: DateRange = Depends(), ps: PlatformSettings = Depends(current_settings),
        q: int | None = Query(None, gt=0, description="exact transaction ID"),
        risk: Literal["Low", "Medium", "High"] | None = None,
        predicted: Literal[0, 1] | None = None, actual: Literal[0, 1] | None = None,
        min_amount: float | None = Query(None, ge=0), max_amount: float | None = Query(None, ge=0),
        sort: Literal["processed_at", "fraud_probability", "amount", "transaction_id", "latency_ms"] = "processed_at",
        order: Literal["asc", "desc"] = "desc"):
    case, cparams = risk_case_sql("lp.fraud_probability", ps.risk_low_max, ps.risk_high_min)
    where, params = dr.where()
    if q is not None:
        where.append("lp.transaction_id = %s"); params.append(q)
    if risk:
        where.append(f"{case} = %s"); params += [*cparams, risk]
    if predicted is not None:
        where.append("lp.predicted_class = %s"); params.append(predicted)
    if actual is not None:
        where.append("t.actual_class = %s"); params.append(actual)
    if min_amount is not None:
        where.append("t.amount >= %s"); params.append(min_amount)
    if max_amount is not None:
        where.append("t.amount <= %s"); params.append(max_amount)
    w = ("WHERE " + " AND ".join(where)) if where else ""
    frm = "FROM latest_predictions lp JOIN transactions t USING (transaction_id)"
    total = db.query_one(f"SELECT count(*) AS n {frm} {w}", params)["n"]
    rows = db.query_all(
        f"""SELECT lp.transaction_id, t.amount::float8 AS amount, lp.fraud_probability, {case} AS risk_level,
                   lp.predicted_class, t.actual_class, lp.model_version, lp.source, lp.status,
                   lp.processed_at, lp.latency_ms
            {frm} {w} ORDER BY {SORT_COLUMNS[sort]} {order.upper()} NULLS LAST, lp.transaction_id
            LIMIT %s OFFSET %s""", [*cparams, *params, pg.page_size, pg.offset])
    return Page(items=rows, page=pg.page, page_size=pg.page_size, total=total,
                total_pages=max(1, math.ceil(total / pg.page_size)))


@router.get("/{transaction_id}")
def investigate(transaction_id: int, ps: PlatformSettings = Depends(current_settings)):
    raw = fetch_transaction(transaction_id)
    if raw is None:
        raise HTTPException(404, f"Transaction ID {transaction_id} not found")
    history = db.query_all(
        """SELECT prediction_id, model_name, model_version, source, fraud_probability, predicted_class, threshold,
                  status, processed_at, latency_ms, inference_ms FROM fraud_predictions
           WHERE transaction_id = %s ORDER BY processed_at DESC, prediction_id DESC""", (transaction_id,))
    for h in history:
        h["risk_level"] = risk_level(h["fraud_probability"], ps.risk_low_max, ps.risk_high_min)
    features = {k: raw[k] for k in V_COLUMNS}
    return {"transaction": {"transaction_id": raw["transaction_id"], "amount": raw["amount"],
                            "transaction_time": raw["transaction_time"], "actual_class": raw["actual_class"],
                            "actual_label": {0: "Legitimate", 1: "Fraud"}.get(raw["actual_class"])},
            "features": features,
            "feature_note": "V1-V28 are anonymised PCA components from the source dataset; no personal or "
                            "account data exists in it.",
            "latest_prediction": history[0] if history else None,
            "history": history}


@router.get("/{transaction_id}/explain")
async def explain(transaction_id: int, version: str | None = Query(None, max_length=32), top: int = Query(10, ge=1, le=40)):
    def work():
        raw = fetch_transaction(transaction_id)
        if raw is None:
            raise HTTPException(404, f"Transaction ID {transaction_id} not found")
        bundle = get_store().get(version)
        out = bundle.explain(pd.DataFrame([raw]))
        out["threshold"] = bundle.threshold
        out["contributions"] = out["contributions"][:top]
        out["predicted_class"] = int(out["probability"] >= bundle.threshold)
        out["method_note"] = ("Exact TreeSHAP contributions in log-odds space: positive values push the score "
                              "toward fraud, negative values toward legitimate. Features are anonymised.")
        return out
    try:
        return await run_in_threadpool(work)
    except FileNotFoundError:
        raise HTTPException(404, "Model version not found")


@router.get("/{transaction_id}/compare")
async def compare_versions(transaction_id: int, ps: PlatformSettings = Depends(current_settings)):
    def work():
        raw = fetch_transaction(transaction_id)
        if raw is None:
            raise HTTPException(404, f"Transaction ID {transaction_id} not found")
        store = get_store()
        frame = pd.DataFrame([raw])
        stored = {r["model_version"]: r for r in db.query_all(
            """SELECT DISTINCT ON (model_version) model_version, fraud_probability, predicted_class, processed_at
               FROM fraud_predictions WHERE transaction_id = %s AND status='completed'
               ORDER BY model_version, processed_at DESC""", (transaction_id,))}
        out = []
        for v in store.versions():
            b = store.get(v)
            p = float(b.predict_proba(frame)[0])
            out.append({"model_version": v, "rescored_probability": p, "threshold": b.threshold,
                        "rescored_class": int(p >= b.threshold),
                        "risk_level": risk_level(p, ps.risk_low_max, ps.risk_high_min),
                        "stored_prediction": stored.get(v)})
        for v, row in stored.items():     # e.g. 'legacy' predictions whose model files we do not have
            if v not in {o["model_version"] for o in out}:
                out.append({"model_version": v, "rescored_probability": None, "stored_prediction": row,
                            "risk_level": risk_level(row["fraud_probability"], ps.risk_low_max, ps.risk_high_min)})
        return {"transaction_id": transaction_id, "actual_class": raw["actual_class"], "versions": out,
                "note": "'rescored' = scored now with that model version (not stored); 'stored' = historical row."}
    return await run_in_threadpool(work)
