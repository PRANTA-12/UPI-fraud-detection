import redis
import redis.asyncio as aioredis

from core.config import get_settings


def _kwargs():
    s = get_settings()
    return dict(host=s.redis_host, port=s.redis_port, password=s.redis_password or None,
                decode_responses=True, socket_connect_timeout=5, health_check_interval=30)


def get_sync_redis() -> redis.Redis:
    return redis.Redis(**_kwargs())


def get_async_redis() -> aioredis.Redis:
    return aioredis.Redis(**_kwargs())
