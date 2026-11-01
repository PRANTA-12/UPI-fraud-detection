import math

from fastapi import APIRouter, Depends, Query, Request

from api.deps import audit
from core import db
from core.config import get_settings
from core.model_store import get_store
from core.platform_settings import PlatformSettings, load_settings, save_settings
from core.security import User, require_role

router = APIRouter(tags=["settings & administration"])


@router.get("/settings")
def read_settings(user: User = Depends(require_role("viewer"))):
    s = get_settings()
    try:
        meta = get_store().get().metadata
        model = {"name": meta["name"], "version": meta["version"], "classification_threshold": meta["threshold"]}
    except Exception:
        model = None
    return {"settings": load_settings().model_dump(), "can_edit": user.role == "admin", "model": model,
            "environment": {"app_env": s.app_env, "auth_required": s.auth_required,
                            "ws_require_auth": s.ws_require_auth,
                            "producer_delay_ms": [s.producer_min_delay_ms, s.producer_max_delay_ms]},
            "protected": "Secrets, connection strings and credentials are never exposed by the API."}


@router.put("/settings")
def update_settings(body: PlatformSettings, request: Request, user: User = Depends(require_role("admin"))):
    before = load_settings().model_dump()
    saved = save_settings(body, user.name)
    from core.cache import clear_cache
    clear_cache()
    audit(request, user.name, "settings_updated", {"before": before, "after": saved.model_dump()})
    return {"settings": saved.model_dump()}


@router.get("/admin/audit")
def audit_log(request: Request, user: User = Depends(require_role("admin")),
              page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100)):
    total = db.query_one("SELECT count(*) AS n FROM audit_log")["n"]
    rows = db.query_all("SELECT audit_id, ts, username, action, ip, detail FROM audit_log "
                        "ORDER BY ts DESC LIMIT %s OFFSET %s", (page_size, (page - 1) * page_size))
    return {"items": rows, "page": page, "page_size": page_size, "total": total,
            "total_pages": max(1, math.ceil(total / page_size))}
