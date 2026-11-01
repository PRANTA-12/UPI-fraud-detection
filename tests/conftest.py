"""Test fixtures.

* PostgreSQL: TEST_DATABASE_URL if set (e.g. the docker-compose db), otherwise a throw-away local server via `pgserver`.
* Redis: fakeredis (shared FakeServer for sync + async clients)
* Data: a few dozen SYNTHETIC rows exist only in the test database (never in app code or dashboards).
"""
import os
import tempfile

import fakeredis
import fakeredis.aioredis
import numpy as np
import psycopg2
import pytest

os.environ.update({"APP_ENV": "test", "JWT_SECRET": "t" * 40, "ADMIN_USERNAME": "admin", "ADMIN_PASSWORD": "Admin-test-pass-1",
                   "LOG_LEVEL": "WARNING", "STREAM_NAME": "test_stream", "DLQ_STREAM_NAME": "test_stream:dlq",
                   "CONSUMER_GROUP": "test_group", "ALERT_CHANNEL": "test_alerts", "MODELS_DIR": "models"})

V = [f"v{i}" for i in range(1, 29)]


@pytest.fixture(scope="session")
def pg_url():
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        yield url
        return
    import pgserver
    tmp = tempfile.mkdtemp(prefix="upi_pg_")
    srv = pgserver.get_server(tmp, cleanup_mode="stop")
    admin = psycopg2.connect(srv.get_uri()); admin.autocommit = True
    admin.cursor().execute("CREATE DATABASE upi_pytest")
    admin.close()
    yield srv.get_uri().replace("/postgres?", "/upi_pytest?")
    srv.cleanup()


@pytest.fixture(scope="session")
def env(pg_url):
    os.environ["DATABASE_URL"] = pg_url
    from core import config, db
    config.get_settings.cache_clear(); db.close_pool()
    from alembic import command
    from alembic.config import Config
    cfg = Config("alembic.ini"); command.upgrade(cfg, "head")
    rng = np.random.default_rng(0)
    with db.get_conn() as conn, conn.cursor() as cur:
        for i in range(1, 61):
            cur.execute(f"INSERT INTO transactions (transaction_id, transaction_time, amount, {', '.join(V)}, actual_class) "
                        f"VALUES (%s,%s,%s,{', '.join(['%s'] * 28)},%s) ON CONFLICT DO NOTHING",
                        [i, float(i * 100), round(float(rng.uniform(1, 500)), 2), *rng.normal(0, 1, 28).tolist(), int(i % 20 == 0)])
        # a clearly fraud-like row (real fraud #542 pattern is not available in the repo; use extreme V14/V4)
        extreme = [0.0] * 28; extreme[13] = -12.0; extreme[3] = 6.0; extreme[10] = 5.0; extreme[11] = -12.0
        cur.execute(f"INSERT INTO transactions (transaction_id, transaction_time, amount, {', '.join(V)}, actual_class) "
                    f"VALUES (900,1000,1.0,{', '.join(['%s'] * 28)},1) ON CONFLICT DO NOTHING", extreme)
    yield
    db.close_pool()


@pytest.fixture()
def fake_server():
    return fakeredis.FakeServer()


@pytest.fixture()
def client(env, fake_server, monkeypatch):
    from starlette.testclient import TestClient
    import api.main as main
    monkeypatch.setattr(main, "get_async_redis", lambda: fakeredis.aioredis.FakeRedis(server=fake_server, decode_responses=True))
    monkeypatch.setattr(main, "get_sync_redis", lambda: fakeredis.FakeStrictRedis(server=fake_server, decode_responses=True))
    with TestClient(main.create_app()) as c:
        yield c


def _login(client, user, pw):
    r = client.post("/auth/login", json={"username": user, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def admin(client):
    return _login(client, "admin", "Admin-test-pass-1")


@pytest.fixture()
def viewer(client, env):
    from core import db
    from core.security import hash_password
    db.execute("INSERT INTO users (username,password_hash,role) VALUES ('viewer_t',%s,'viewer') ON CONFLICT DO NOTHING",
               (hash_password("Viewer-test-pass-1"),))
    return _login(client, "viewer_t", "Viewer-test-pass-1")


@pytest.fixture(autouse=True)
def _clean(env):
    from core import db
    from core.cache import clear_cache
    clear_cache()
    db.execute("DELETE FROM fraud_predictions")
    yield
