"""Data-access helpers shared by the API and the streaming consumer."""
from __future__ import annotations

from datetime import datetime

from core import db
from core.features import V_COLUMNS

RAW_SELECT = ("transaction_id, transaction_time, amount::float8 AS amount, "
              + ", ".join(V_COLUMNS) + ", actual_class")


def fetch_transaction(txn_id: int) -> dict | None:
    return db.query_one(f"SELECT {RAW_SELECT} FROM transactions WHERE transaction_id = %s", (txn_id,))


def ensure_transaction(cur, payload: dict) -> None:
    """Lets a native source (not the replay producer) introduce new transactions via the stream."""
    cols = ["transaction_id", "transaction_time", "amount", *V_COLUMNS, "actual_class"]
    cur.execute(
        f"INSERT INTO transactions ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) "
        "ON CONFLICT (transaction_id) DO NOTHING",
        [payload.get(c) for c in cols])


def insert_prediction(cur, *, transaction_id: int, probability: float, predicted_class: int, model_name: str,
                      model_version: str, threshold: float, risk_level: str, source: str,
                      enqueued_at: datetime | None, inference_ms: float, latency_ms: float,
                      idempotency_key: str | None = None) -> dict | None:
    """Returns {'prediction_id', 'processed_at'} or None when the idempotency key already exists."""
    cur.execute(
        """INSERT INTO fraud_predictions
              (transaction_id, fraud_probability, predicted_class, model_name, threshold, model_version,
               risk_level, source, status, idempotency_key, enqueued_at, processed_at, inference_ms, latency_ms)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'completed',%s,%s, now(), %s, %s)
           ON CONFLICT (idempotency_key) WHERE idempotency_key IS NOT NULL DO NOTHING
           RETURNING prediction_id, processed_at""",
        (transaction_id, probability, predicted_class, model_name, threshold, model_version, risk_level,
         source, idempotency_key, enqueued_at, inference_ms, latency_ms))
    row = cur.fetchone()
    return {"prediction_id": row[0], "processed_at": row[1]} if row else None
