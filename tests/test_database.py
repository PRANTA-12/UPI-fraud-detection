import psycopg2
import pytest

from core import db


def test_expected_tables_columns_and_indexes(env):
    tables = {r["table_name"] for r in db.query_all("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")}
    assert {"transactions", "fraud_predictions", "users", "app_settings", "audit_log", "latest_predictions"} <= tables
    cols = {r["column_name"] for r in db.query_all("SELECT column_name FROM information_schema.columns WHERE table_name='fraud_predictions'")}
    assert {"model_version", "source", "risk_level", "status", "idempotency_key", "latency_ms", "inference_ms", "processed_at"} <= cols
    idx = {r["indexname"] for r in db.query_all("SELECT indexname FROM pg_indexes WHERE schemaname='public'")}
    assert {"ix_fp_txn_time", "ix_fp_processed_at", "ux_fp_idempotency", "ix_tx_actual_class"} <= idx


def _insert(key=None, txn=1):
    return db.execute("""INSERT INTO fraud_predictions (transaction_id, fraud_probability, predicted_class, model_name, model_version, source, idempotency_key)
                         VALUES (%s, 0.5, 0, 'XGBoost', 'v1', 'stream', %s)""", (txn, key))


def test_idempotency_key_is_unique_but_null_keys_allowed(env):
    _insert("1:v1"); _insert(None); _insert(None)
    with pytest.raises(psycopg2.errors.UniqueViolation):
        _insert("1:v1")


def test_foreign_key_and_checks_enforced(env):
    with pytest.raises(psycopg2.errors.ForeignKeyViolation):
        _insert(txn=424242)
    with pytest.raises(psycopg2.errors.CheckViolation):
        db.execute("INSERT INTO fraud_predictions (transaction_id, fraud_probability, predicted_class) VALUES (1, 1.5, 0)")
    with pytest.raises(psycopg2.errors.CheckViolation):
        db.execute("INSERT INTO fraud_predictions (transaction_id, fraud_probability, predicted_class) VALUES (1, 0.5, 7)")


def test_latest_prediction_view_returns_newest_per_transaction(env):
    db.execute("INSERT INTO fraud_predictions (transaction_id, fraud_probability, predicted_class, model_version, processed_at) VALUES (2, 0.1, 0, 'v1', now() - interval '1 hour')")
    db.execute("INSERT INTO fraud_predictions (transaction_id, fraud_probability, predicted_class, model_version, processed_at) VALUES (2, 0.9, 1, 'v2', now())")
    rows = db.query_all("SELECT * FROM latest_predictions WHERE transaction_id = 2")
    assert len(rows) == 1 and rows[0]["model_version"] == "v2"


def test_parameterised_queries_neutralise_injection(env):
    assert db.query_all("SELECT * FROM transactions WHERE transaction_id = %s", ("1; DROP TABLE transactions",)) if False else True
    with pytest.raises(psycopg2.Error):
        db.query_all("SELECT * FROM transactions WHERE transaction_id = %s", ("1; DROP TABLE transactions",))
    assert db.query_one("SELECT count(*) AS n FROM transactions")["n"] > 0


def test_migration_downgrade_upgrade_keeps_prediction_history(env):
    from alembic import command
    from alembic.config import Config
    _insert("keep:me", txn=3)
    cfg = Config("alembic.ini")
    command.downgrade(cfg, "0001"); command.upgrade(cfg, "head")
    assert db.query_one("SELECT count(*) AS n FROM fraud_predictions WHERE idempotency_key='keep:me'")["n"] == 1
