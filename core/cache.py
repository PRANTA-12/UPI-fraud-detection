"""Tiny in-process TTL cache (protects PostgreSQL from dashboard refresh storms)."""
import threading
import time
from functools import wraps

_store: dict = {}
_lock = threading.Lock()


def ttl_cache(seconds: float):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            key = (fn.__module__, fn.__name__, args, tuple(sorted(kwargs.items())))
            now = time.monotonic()
            with _lock:
                hit = _store.get(key)
                if hit and now - hit[0] < seconds:
                    return hit[1]
            value = fn(*args, **kwargs)
            with _lock:
                _store[key] = (now, value)
            return value
        return wrapper
    return deco


def clear_cache() -> None:
    with _lock:
        _store.clear()
