import json
import logging
from datetime import datetime
from typing import Literal

from fastapi import Depends, HTTPException, Query, Request

from core import db
from core.platform_settings import PlatformSettings, load_settings
from core.security import client_ip

log = logging.getLogger("api.audit")


def audit(request: Request, username: str | None, action: str, detail: dict | None = None) -> None:
    """Structured audit trail (DB + log). Must never break the request."""
    try:
        db.execute("INSERT INTO audit_log (username, action, ip, detail) VALUES (%s,%s,%s,%s::jsonb)",
                   (username, action, client_ip(request), json.dumps(detail or {}, default=str)))
    except Exception as e:  # pragma: no cover
        log.warning("audit write failed", extra={"error": str(e)})
    log.info("audit", extra={"audit_action": action, "user": username, "ip": client_ip(request), "detail": detail})


def current_settings() -> PlatformSettings:
    return load_settings()


class DateRange:
    """?date_from=&date_to= (ISO-8601). Applied to prediction *processing* time: the source dataset has no
    real transaction timestamps, so this is the only honest time axis."""

    def __init__(self, date_from: datetime | None = Query(None), date_to: datetime | None = Query(None),
                 model_version: str | None = Query(None, max_length=32, description="only predictions from this model version")):
        if date_from and date_to and date_from > date_to:
            raise HTTPException(422, "date_from must be <= date_to")
        self.date_from, self.date_to, self.model_version = date_from, date_to, model_version

    def where(self, col: str = "lp.processed_at") -> tuple[list[str], list]:
        parts, params = [], []
        if self.date_from:
            parts.append(f"{col} >= %s"); params.append(self.date_from)
        if self.date_to:
            parts.append(f"{col} <= %s"); params.append(self.date_to)
        if self.model_version:
            parts.append(f"{col.rsplit('.', 1)[0]}.model_version = %s"); params.append(self.model_version)
        return parts, params


class PageParams:
    def __init__(self, page: int = Query(1, ge=1, le=100_000), page_size: int = Query(25, ge=1, le=100)):
        self.page, self.page_size = page, page_size

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


HELD_OUT_NOTE = ("Held-out = transactions after the model's training period, scored by the active model version. "
                 "Everything earlier is in-sample for that model, so metrics on it are optimistic.")


def held_out_sql(active_version: str | None, cutoff: float | None) -> tuple[str, list]:
    """SELECT fragment (+params) with held-out aggregates over aliases lp (predictions) and t (transactions)."""
    cut = cutoff if cutoff is not None else 1e18
    cond = "t.transaction_time > %s AND lp.model_version = %s"
    sql = (f"count(*) FILTER (WHERE {cond}) AS ho_n, "
           f"count(*) FILTER (WHERE {cond} AND t.actual_class = 1) AS ho_actual, "
           f"count(*) FILTER (WHERE {cond} AND lp.predicted_class = 1 AND t.actual_class = 1) AS ho_tp, "
           f"count(*) FILTER (WHERE {cond} AND lp.predicted_class = 1 AND t.actual_class = 0) AS ho_fp, "
           f"count(*) FILTER (WHERE {cond} AND lp.predicted_class = 0 AND t.actual_class = 1) AS ho_fn")
    return sql, [cut, active_version] * 5


def held_out_block(row: dict, active_version, cutoff) -> dict:
    tp, fp, fn = row["ho_tp"], row["ho_fp"], row["ho_fn"]
    return {"available": cutoff is not None, "model_version": active_version, "train_time_max": cutoff,
            "processed": row["ho_n"], "actual_fraud": row["ho_actual"], "caught": tp, "missed": fn, "false_alarms": fp,
            "detection_rate": (tp / row["ho_actual"]) if row["ho_actual"] else None,
            "precision": (tp / (tp + fp)) if (tp + fp) else None, "note": HELD_OUT_NOTE}


def active_model_info() -> tuple[str | None, float | None]:
    from core.model_store import get_store
    try:
        v = get_store().active_version()
        return v, get_store().metadata(v).get("data", {}).get("train_time_max")
    except Exception:
        return None, None
