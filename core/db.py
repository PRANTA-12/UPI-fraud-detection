"""PostgreSQL access: one pooled connection factory, parameterised queries only."""
from __future__ import annotations

import threading
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

from core.config import get_settings

_pool: ThreadedConnectionPool | None = None
_lock = threading.Lock()


def get_pool() -> ThreadedConnectionPool:
    global _pool
    with _lock:
        if _pool is None:
            s = get_settings()
            _pool = ThreadedConnectionPool(1, s.db_pool_max, s.dsn, connect_timeout=10,
                                           options="-c statement_timeout=20000")
        return _pool


def close_pool() -> None:
    global _pool
    with _lock:
        if _pool is not None:
            _pool.closeall()
            _pool = None


@contextmanager
def get_conn():
    pool = get_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def query_all(sql: str, params=None) -> list[dict]:
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def query_one(sql: str, params=None) -> dict | None:
    rows = query_all(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params=None) -> int:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.rowcount


def ping() -> bool:
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
            return cur.fetchone()[0] == 1
    except psycopg2.Error:
        return False
