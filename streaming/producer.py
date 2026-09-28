"""
Real-time transaction producer.

Your dataset (loaded via load_data.py) is historical, so there's no live
UPI switch to plug into. This script replays the `transactions` table row
by row onto a Redis Stream, at irregular intervals, to *simulate* a live
transaction feed.

In a real deployment, this file is the only thing that changes: swap it
for whatever actually emits transactions in your environment (a payment
gateway webhook receiver, a Kafka topic bridged from the switch, an NPCI
callback endpoint, etc). Everything downstream - the consumer, the model,
the DB writes, the live alerts - stays exactly the same because it only
ever talks to the Redis Stream, never to this script directly.
"""

import json
import logging
import random
import time

import psycopg2
import redis

from streaming.config import (
    DB_CONFIG,
    PRODUCER_MAX_DELAY_MS,
    PRODUCER_MIN_DELAY_MS,
    REDIS_HOST,
    REDIS_PORT,
    STREAM_NAME,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - PRODUCER - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

FEATURE_COLUMNS = ["transaction_time", "amount"] + [f"v{i}" for i in range(1, 29)]
BATCH_SIZE = 500


def get_db_connection():
    return psycopg2.connect(**DB_CONFIG)


def get_redis_client():
    return redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)


def fetch_batch(cursor, after_id: int, batch_size: int = BATCH_SIZE):
    query = f"""
        SELECT transaction_id, {", ".join(FEATURE_COLUMNS)}
        FROM transactions
        WHERE transaction_id > %s
        ORDER BY transaction_id
        LIMIT %s;
    """
    cursor.execute(query, (after_id, batch_size))
    return cursor.fetchall()


def run():
    conn = get_db_connection()
    cursor = conn.cursor()
    r = get_redis_client()

    last_id = 0
    logger.info(
        "Producer started - streaming '%s' rows to redis %s:%s stream '%s'",
        DB_CONFIG["database"], REDIS_HOST, REDIS_PORT, STREAM_NAME,
    )

    while True:
        rows = fetch_batch(cursor, last_id)

        if not rows:
            logger.info("End of transactions table reached - looping back to the start (demo mode).")
            last_id = 0
            time.sleep(2)
            continue

        for row in rows:
            transaction_id = row[0]
            payload = dict(zip(FEATURE_COLUMNS, row[1:]))
            payload["transaction_id"] = transaction_id

            # NUMERIC(12,2) amount arrives as Decimal - default=float makes it JSON-safe
            r.xadd(STREAM_NAME, {"data": json.dumps(payload, default=float)})

            logger.info("Emitted transaction_id=%s", transaction_id)
            last_id = transaction_id

            time.sleep(random.uniform(PRODUCER_MIN_DELAY_MS, PRODUCER_MAX_DELAY_MS) / 1000)


if __name__ == "__main__":
    run()
