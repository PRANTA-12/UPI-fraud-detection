import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from api.deps import audit
from api.schemas import LoginRequest, TokenResponse
from core import db
from core.ratelimit import rate_limit
from core.security import User, create_token, hash_password, require_role, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])
log = logging.getLogger("api.auth")
_DUMMY_HASH = hash_password("dummy-password-for-timing")


@router.post("/login", response_model=TokenResponse, dependencies=[Depends(rate_limit(10, 60, "login"))])
def login(body: LoginRequest, request: Request):
    user = db.query_one("SELECT username, password_hash, role, active FROM users WHERE username = %s",
                        (body.username,))
    ok = verify_password(body.password, user["password_hash"] if user else _DUMMY_HASH)  # constant-ish time
    if not user or not ok or not user["active"]:
        audit(request, body.username, "login_failed")
        raise HTTPException(401, "Incorrect username or password")
    db.execute("UPDATE users SET last_login_at = now() WHERE username = %s", (user["username"],))
    token, ttl = create_token(user["username"], user["role"])
    audit(request, user["username"], "login_success")
    return TokenResponse(access_token=token, expires_in=ttl, username=user["username"], role=user["role"])


@router.get("/me")
def me(user: User = Depends(require_role("viewer"))):
    return {"username": user.name, "role": user.role}
