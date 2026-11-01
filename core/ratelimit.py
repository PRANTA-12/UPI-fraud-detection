"""Fixed-window rate limiter backed by Redis (shared by all API workers)."""
from fastapi import HTTPException, Request, status

from core.security import client_ip


def rate_limit(limit: int, window_s: int = 60, scope: str = "default"):
    async def dep(request: Request):
        r = getattr(request.app.state, "redis", None)
        if r is None:
            return
        key = f"rl:{scope}:{client_ip(request)}:{window_s}"
        try:
            n = await r.incr(key)
            if n == 1:
                await r.expire(key, window_s)
            if n > limit:
                ttl = await r.ttl(key)
                raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Rate limit exceeded",
                                    headers={"Retry-After": str(max(ttl, 1))})
        except HTTPException:
            raise
        except Exception:      # Redis outage must not take the API down
            return
    return dep
