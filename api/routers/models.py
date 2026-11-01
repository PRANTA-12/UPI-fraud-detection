import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import current_settings
from core import db
from core.features import FEATURE_COLUMNS, RAW_COLUMNS, build_features
from core.model_store import ModelNotAvailable, get_store
from core.platform_settings import PlatformSettings
from core.security import require_role

router = APIRouter(prefix="/model", tags=["model intelligence"], dependencies=[Depends(require_role("viewer"))])


def _artifact(version: str, name: str):
    try:
        return get_store().artifact(version, name)
    except ModelNotAvailable:
        raise HTTPException(404, f"No '{name}' for model version '{version}' (e.g. an imported legacy model has no evaluation artifacts)")


def _version(v: str | None) -> str:
    store = get_store()
    v = v or store.active_version()
    if v not in store.versions():
        raise HTTPException(404, f"Model version '{v}' not found")
    return v


@router.get("/info")
def info(version: str | None = Query(None, max_length=32), ps: PlatformSettings = Depends(current_settings)):
    v = _version(version)
    meta = get_store().get(v).metadata
    return {**meta, "active_version": get_store().active_version(),
            "classification_threshold": meta["threshold"],
            "risk_bands": {"low_max": ps.risk_low_max, "high_min": ps.risk_high_min},
            "note": "The classification threshold is baked into the model version (chosen on out-of-fold training "
                    "predictions). Risk bands are separate, display-level probability bands."}


@router.get("/metrics")
def metrics(version: str | None = Query(None, max_length=32)):
    v = _version(version)
    m = _artifact(v, "metrics.json")
    comp = m["comparison"]
    return {"model_version": v, "test": m["test"], "test_at_0.5": m["test_at_0.5"], "comparison": comp,
            "roc_curve": m["roc_curve"], "pr_curve": m["pr_curve"],
            "evaluation_note": "Temporal hold-out (last 20% by time) never used for fitting, tuning or choosing the "
                               "threshold. The test fold has few fraud cases, so metrics are noisy."}


@router.get("/importance")
def importance(version: str | None = Query(None, max_length=32), top: int = Query(15, ge=1, le=40)):
    v = _version(version)
    return {"model_version": v, "method": "mean |SHAP| (TreeSHAP) on a test sample incl. all test frauds",
            "features": _artifact(v, "importance.json")[:top]}


@router.get("/history")
def history():
    reg = get_store().registry()
    stored = {r["model_version"]: r for r in db.query_all(
        """SELECT model_version, count(*) AS predictions, count(*) FILTER (WHERE predicted_class=1) AS flagged,
                  min(processed_at) AS first_used, max(processed_at) AS last_used
           FROM fraud_predictions GROUP BY 1""")}
    return {"active": reg["active"],
            "versions": [{**v, "active": v["version"] == reg["active"], "live_usage": stored.get(v["version"])}
                         for v in reg["versions"]]}


@router.get("/prediction-distribution")
def prediction_distribution():
    rows = db.query_all("""SELECT model_version, LEAST(floor(fraud_probability * 20), 19)::int AS b, count(*) AS n
                           FROM fraud_predictions WHERE status='completed' GROUP BY 1, 2 ORDER BY 1, 2""")
    out: dict[str, list] = {}
    for r in rows:
        out.setdefault(r["model_version"], [0] * 20)[r["b"]] = r["n"]
    return {"bins": [i / 20 for i in range(21)], "by_version": out}


def _psi(actual: np.ndarray, ref: dict) -> float:
    edges = np.array([-np.inf if e is None and i == 0 else np.inf if e is None else e
                      for i, e in enumerate(ref["edges"])])
    counts, _ = np.histogram(actual, bins=edges)
    a = np.clip(counts / max(counts.sum(), 1), 1e-4, None)
    e = np.clip(np.array(ref["expected"]), 1e-4, None)
    return float(np.sum((a - e) * np.log(a / e)))


@router.get("/drift")
def drift(sample: int = Query(5000, ge=200, le=20000), version: str | None = Query(None, max_length=32)):
    v = _version(version)
    ref = _artifact(v, "drift_reference.json")
    rows = db.query_all(
        f"""SELECT t.transaction_time, t.amount::float8 AS amount, {', '.join('t.' + c for c in RAW_COLUMNS[2:])},
                   lp.fraud_probability
            FROM latest_predictions lp JOIN transactions t USING (transaction_id)
            ORDER BY lp.processed_at DESC LIMIT %s""", (sample,))
    n = len(rows)
    if n < 200:
        return {"model_version": v, "status": "insufficient_data", "sample_size": n, "min_required": 200,
                "indicators": []}
    df = pd.DataFrame(rows)
    feats = build_features(df[RAW_COLUMNS]); feats["fraud_probability"] = df["fraud_probability"]
    out = []
    for name, r in ref.items():
        psi = _psi(feats[name].values, r)
        out.append({"feature": name, "psi": psi,
                    "status": "stable" if psi < 0.1 else "moderate_shift" if psi < 0.25 else "significant_shift"})
    out.sort(key=lambda d: -d["psi"])
    worst = out[0]["status"] if out else "stable"
    return {"model_version": v, "status": worst, "sample_size": n, "indicators": out,
            "method": "Population Stability Index of recent processed transactions vs the training distribution "
                      "(deciles). <0.1 stable, 0.1-0.25 moderate, >0.25 significant.",
            "caveat": "Replayed rows come from the same dataset, and PRODUCER_FRAUD_BOOST over-represents fraud, which "
                      "itself shifts feature distributions (PSI rises). Treat this indicator as meaningful only "
                      "with real traffic or with PRODUCER_FRAUD_BOOST=0."}
