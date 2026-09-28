"""
Real-time fraud-scoring consumer.

Reads transactions off the Redis Stream as they arrive (via a consumer
group, so you can run several of these in parallel and Redis will split
the stream between them - each transaction still gets scored exactly
once), scores them with the same XGBoost model the batch API uses, writes
the result to `fraud_predictions`, and publishes it to a pub/sub channel
so the API can push it to any live viewers over WebSocket.

Scale out horizontally with:
    docker compose up --scale consumer=3
"""

import json
import logging
from pathlib import Path

import joblib
import pandas as pd
import psycopg2
import redis

from streaming.config import (
    ALERT_CHANNEL,
    CONSUMER_GROUP,
    CONSUMER_NAME,
    DB_CONFIG,
    DLQ_STREAM_NAME,
    REDIS_HOST,
    REDIS_PORT,
    STREAM_NAME,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - CONSUMER - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[1]
MODEL_PATH = BASE_DIR / "models" / "fraud_model.pkl"
FEATURE_PATH = BASE_DIR / "models" / "features.pkl"

THRESHOLD = 0.50


model = joblib.load(MODEL_PATH)
features = joblib.load(FEATURE_PATH)
logger.info("Model loaded - expecting %d features.", len(features))


def get_db_connection():
    return psycopg2.connect(**DB_CONFIG)


def get_redis_client():
    return redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)


def ensure_group(r: redis.Redis):
    try:
        r.xgroup_create(STREAM_NAME, CONSUMER_GROUP, id="0", mkstream=True)
        logger.info("Created consumer group '%s' on stream '%s'", CONSUMER_GROUP, STREAM_NAME)
    except redis.exceptions.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise  # group already exists - fine, keep going


def score(payload: dict):
    row = {"Time": payload["transaction_time"], "Amount": payload["amount"]}
    for i in range(1, 29):
        row[f"V{i}"] = payload[f"v{i}"]

    input_df = pd.DataFrame([row], columns=features).apply(pd.to_numeric)
    probability = float(model.predict_proba(input_df)[0][1])
    prediction = int(probability >= THRESHOLD)

    if probability >= 0.70:
        risk_level = "High"
    elif probability >= 0.30:
        risk_level = "Medium"
    else:
        risk_level = "Low"

    return probability, prediction, risk_level


def save_prediction(cursor, transaction_id, probability, prediction):
    cursor.execute(
        """
        INSERT INTO fraud_predictions
            (transaction_id, fraud_probability, predicted_class, model_name, threshold)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING prediction_id;
        """,
        (transaction_id, probability, prediction, "XGBoost-Streaming", THRESHOLD),
    )
    return cursor.fetchone()[0]


def run():
    r = get_redis_client()
    ensure_group(r)

    conn = get_db_connection()
    conn.autocommit = False
    cursor = conn.cursor()

    logger.info(
        "Consumer '%s' listening on stream '%s' (group '%s')",
        CONSUMER_NAME, STREAM_NAME, CONSUMER_GROUP,
    )

    while True:
        try:
            entries = r.xreadgroup(
                CONSUMER_GROUP,
                CONSUMER_NAME,
                {STREAM_NAME: ">"},
                count=10,
                block=1000,
            )

            if not entries:
                continue

        except redis.exceptions.TimeoutError:
            logger.warning("Redis read timeout. Retrying...")
            continue

        for _stream, messages in entries:
            for message_id, fields in messages:
                try:
                    payload = json.loads(fields["data"])
                    transaction_id = payload["transaction_id"]

                    probability, prediction, risk_level = score(payload)
                    prediction_id = save_prediction(cursor, transaction_id, probability, prediction)
                    conn.commit()

                    result = {
                        "prediction_id": prediction_id,
                        "transaction_id": transaction_id,
                        "fraud_probability": round(probability, 6),
                        "prediction": prediction,
                        "risk_level": risk_level,
                        "model": "XGBoost-Streaming",
                    }
                    r.publish(ALERT_CHANNEL, json.dumps(result))

                    log_fn = logger.warning if risk_level == "High" else logger.info
                    log_fn(
                        "Scored transaction_id=%s prob=%.4f risk=%s",
                        transaction_id, probability, risk_level,
                    )

                    r.xack(STREAM_NAME, CONSUMER_GROUP, message_id)

                except Exception:
                    conn.rollback()
                    logger.exception("Failed to score message_id=%s - routing to DLQ", message_id)
                    r.xadd(DLQ_STREAM_NAME, fields)
                    r.xack(STREAM_NAME, CONSUMER_GROUP, message_id)


if __name__ == "__main__":
    run()
