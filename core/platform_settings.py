"""Runtime-configurable platform settings (stored in PostgreSQL, admin-writable)."""
from __future__ import annotations

import json
import time
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from core import db


class PlatformSettings(BaseModel):
    risk_low_max: float = Field(0.30, gt=0, lt=1)
    risk_high_min: float = Field(0.70, gt=0, lt=1)
    refresh_seconds: int = Field(5, ge=2, le=300)
    alerts_enabled: bool = True
    alert_min_risk: Literal["Medium", "High"] = "High"
    alert_sound: bool = False
    default_risk_filter: Literal["All", "Low", "Medium", "High"] = "All"
    default_page_size: int = Field(25, ge=10, le=100)

    @model_validator(mode="after")
    def _order(self):
        if self.risk_low_max >= self.risk_high_min:
            raise ValueError("risk_low_max must be lower than risk_high_min")
        return self


_cache: tuple[float, PlatformSettings] | None = None
_TTL = 10.0


def load_settings(force: bool = False) -> PlatformSettings:
    global _cache
    if not force and _cache and time.monotonic() - _cache[0] < _TTL:
        return _cache[1]
    try:
        rows = db.query_all("SELECT key, value FROM app_settings")
        data = {r["key"]: r["value"] for r in rows}
        ps = PlatformSettings(**data)
    except Exception:
        ps = PlatformSettings()
    _cache = (time.monotonic(), ps)
    return ps


def save_settings(new: PlatformSettings, username: str) -> PlatformSettings:
    global _cache
    with db.get_conn() as conn, conn.cursor() as cur:
        for k, v in new.model_dump().items():
            cur.execute(
                """INSERT INTO app_settings (key, value, updated_by, updated_at)
                   VALUES (%s, %s::jsonb, %s, now())
                   ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value,
                       updated_by = EXCLUDED.updated_by, updated_at = now()""",
                (k, json.dumps(v), username))
    _cache = None
    return load_settings(force=True)
