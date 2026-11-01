"""Password hashing (bcrypt), JWT, and role-based access control."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from core.config import get_settings

ROLE_RANK = {"viewer": 1, "analyst": 2, "admin": 3}
_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode()[:72], hashed.encode())
    except ValueError:
        return False


def create_token(username: str, role: str) -> tuple[str, int]:
    s = get_settings()
    exp = datetime.now(timezone.utc) + timedelta(minutes=s.access_token_minutes)
    token = jwt.encode({"sub": username, "role": role, "exp": exp, "iat": datetime.now(timezone.utc)},
                       s.jwt_secret or "test-secret-not-for-production-use-000000", algorithm=s.jwt_algorithm)
    return token, s.access_token_minutes * 60


def decode_token(token: str) -> dict:
    s = get_settings()
    return jwt.decode(token, s.jwt_secret or "test-secret-not-for-production-use-000000",
                      algorithms=[s.jwt_algorithm])


class User(dict):
    @property
    def name(self) -> str:
        return self["sub"]

    @property
    def role(self) -> str:
        return self["role"]


def _user_from_creds(creds: HTTPAuthorizationCredentials | None) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated",
                            headers={"WWW-Authenticate": "Bearer"})
    try:
        return User(decode_token(creds.credentials))
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token",
                            headers={"WWW-Authenticate": "Bearer"})


def require_role(minimum: str):
    def dep(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> User:
        if not get_settings().auth_required:
            return User({"sub": "anonymous", "role": "admin"})   # local demos only; blocked in production
        user = _user_from_creds(creds)
        if ROLE_RANK.get(user.role, 0) < ROLE_RANK[minimum]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires role '{minimum}' or higher")
        return user
    return dep


def legacy_guard(minimum: str = "viewer"):
    """Legacy endpoints stay public unless LEGACY_ENDPOINTS_PUBLIC=false."""
    inner = require_role(minimum)

    def dep(request: Request, creds: HTTPAuthorizationCredentials | None = Depends(_bearer)):
        if get_settings().legacy_endpoints_public:
            return None
        return inner(creds)
    return dep


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"
