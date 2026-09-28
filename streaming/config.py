import os
from dotenv import load_dotenv

load_dotenv()

# --------------------------------------------------
# REDIS
# --------------------------------------------------

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

STREAM_NAME = os.getenv("STREAM_NAME", "transactions_stream")
DLQ_STREAM_NAME = os.getenv("DLQ_STREAM_NAME", "transactions_stream:dlq")
CONSUMER_GROUP = os.getenv("CONSUMER_GROUP", "fraud_scorers")
CONSUMER_NAME = os.getenv("CONSUMER_NAME", "consumer-1")
ALERT_CHANNEL = os.getenv("ALERT_CHANNEL", "fraud_alerts")

# --------------------------------------------------
# PRODUCER (simulator) PACING
# --------------------------------------------------

PRODUCER_MIN_DELAY_MS = int(os.getenv("PRODUCER_MIN_DELAY_MS", 200))
PRODUCER_MAX_DELAY_MS = int(os.getenv("PRODUCER_MAX_DELAY_MS", 1500))

# --------------------------------------------------
# POSTGRESQL
# --------------------------------------------------

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "database": os.getenv("DB_NAME", "upi_fraud_db"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", "postgres"),
    "port": int(os.getenv("DB_PORT", 5432)),
}
