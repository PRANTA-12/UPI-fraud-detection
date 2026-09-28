import asyncio
import json
import logging
import os
from pathlib import Path

import joblib
import pandas as pd
import psycopg2
import redis
import redis.asyncio as aioredis
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)

# =========================================================
# FASTAPI APP
# =========================================================

app = FastAPI(
    title="UPI Fraud Detection API",
    description="Fraud detection API using XGBoost, PostgreSQL and a real-time Redis Streams pipeline",
    version="2.0"
)


# =========================================================
# LOAD ML MODEL
# =========================================================

BASE_DIR = Path(__file__).resolve().parents[1]

MODEL_PATH = BASE_DIR / "models" / "fraud_model.pkl"
FEATURE_PATH = BASE_DIR / "models" / "features.pkl"

model = joblib.load(MODEL_PATH)
features = joblib.load(FEATURE_PATH)

logger.info("XGBoost model loaded successfully")
logger.info("Model features loaded: %d", len(features))

STATIC_DIR = BASE_DIR / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# =========================================================
# POSTGRESQL CONFIGURATION
# =========================================================

DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "database": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "port": int(os.getenv("DB_PORT", 5432))
}


def get_connection():
    return psycopg2.connect(**DB_CONFIG)


# =========================================================
# REDIS / STREAMING CONFIGURATION
# =========================================================

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
STREAM_NAME = os.getenv("STREAM_NAME", "transactions_stream")
CONSUMER_GROUP = os.getenv("CONSUMER_GROUP", "fraud_scorers")
ALERT_CHANNEL = os.getenv("ALERT_CHANNEL", "fraud_alerts")


# =========================================================
# LIVE WEBSOCKET BROADCASTING
# =========================================================
# The streaming consumer publishes every scored transaction to a Redis
# pub/sub channel. This app subscribes once on startup and fans each
# message out to every connected WebSocket client, so the live feed works
# the same whether there is one browser tab open or a hundred.

class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active.append(websocket)
        logger.info("WebSocket client connected (%d active)", len(self.active))

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active:
            self.active.remove(websocket)
            logger.info("WebSocket client disconnected (%d active)", len(self.active))

    async def broadcast(self, message: str):
        for ws in list(self.active):
            try:
                await ws.send_text(message)
            except Exception:
                self.disconnect(ws)


manager = ConnectionManager()

@app.websocket("/ws/live")
async def websocket_live_feed(websocket: WebSocket):
    """Live feed of every prediction as the streaming consumer scores it."""

    await manager.connect(websocket)

    try:
        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        manager.disconnect(websocket)


async def alert_listener():
    """Background task: relay Redis pub/sub alerts to WebSocket clients."""

    redis_client = None
    pubsub = None

    try:
        redis_client = aioredis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            decode_responses=True,
        )

        pubsub = redis_client.pubsub()

        await pubsub.subscribe(ALERT_CHANNEL)

        logger.info(
            "Subscribed to '%s' for live alert broadcasting",
            ALERT_CHANNEL,
        )

        while True:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=1.0,
            )

            if message is not None:
                if message["type"] == "message":
                    await manager.broadcast(message["data"])

            await asyncio.sleep(0.01)

    except asyncio.CancelledError:
        logger.info("Alert listener cancelled")

    except Exception:
        logger.exception("Alert listener stopped")

    finally:
        try:
            if pubsub is not None:
                await pubsub.unsubscribe(ALERT_CHANNEL)
                await pubsub.aclose()
        except Exception:
            pass

        try:
            if redis_client is not None:
                await redis_client.aclose()
        except Exception:
            pass

        logger.info("Redis alert listener closed")


# =========================================================
# REQUEST / RESPONSE MODELS
# =========================================================

class TransactionRequest(BaseModel):
    transaction_id: int = Field(
        ...,
        gt=0,
        description="Positive transaction ID"
    )


class PredictionResponse(BaseModel):
    prediction_id: int
    transaction_id: int
    prediction: int
    result: str
    fraud_probability: float
    risk_level: str
    threshold: float
    model: str


# =========================================================
# ROOT ENDPOINT
# =========================================================

@app.get("/")
def root():
    return {
        "message": "UPI Fraud Detection API is running",
        "live_feed": "/static/live.html",
        "websocket": "/ws/live"
    }


# =========================================================
# HEALTH CHECK
# =========================================================

@app.get("/health")
def health():
    conn = None
    cursor = None

    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT 1")
        cursor.fetchone()

        return {
            "status": "healthy",
            "model": "XGBoost",
            "database": "PostgreSQL",
            "database_connection": "ok"
        }

    except Exception as e:
        print("HEALTH CHECK ERROR:", e)

        raise HTTPException(
            status_code=503,
            detail="Database connection unavailable"
        )

    finally:
        if cursor:
            cursor.close()

        if conn:
            conn.close()

# =========================================================
# APPLICATION STARTUP / SHUTDOWN
# =========================================================

alert_listener_task = None


@app.on_event("startup")
async def on_startup():
    global alert_listener_task

    alert_listener_task = asyncio.create_task(
        alert_listener()
    )

    logger.info("Redis alert listener started")


@app.on_event("shutdown")
async def on_shutdown():
    global alert_listener_task

    if alert_listener_task is not None:
        alert_listener_task.cancel()

        try:
            await alert_listener_task
        except asyncio.CancelledError:
            pass

        logger.info("Redis alert listener stopped")



# =========================================================
# STREAM STATUS (observability into the real-time pipeline)
# =========================================================

@app.get("/stream/status")
def stream_status():
    try:
        r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

        length = r.xlen(STREAM_NAME)

        try:
            groups = r.xinfo_groups(STREAM_NAME)
        except redis.exceptions.ResponseError:
            groups = []

        return {
            "stream": STREAM_NAME,
            "pending_length": length,
            "consumer_groups": groups,
        }

    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Redis unavailable: {e}"
        )


# =========================================================
# PREDICT ENDPOINT (unchanged - on-demand scoring by transaction_id)
# =========================================================

@app.post("/predict", response_model=PredictionResponse)
def predict_transaction(request: TransactionRequest):

    transaction_id = request.transaction_id

    conn = None
    cursor = None

    try:

        # -------------------------------------------------
        # CONNECT TO DATABASE
        # -------------------------------------------------

        conn = get_connection()
        cursor = conn.cursor()

        # -------------------------------------------------
        # GET TRANSACTION
        # -------------------------------------------------

        query = """
        SELECT
            transaction_time,
            amount,
            v1, v2, v3, v4, v5, v6, v7, v8,
            v9, v10, v11, v12, v13, v14, v15,
            v16, v17, v18, v19, v20, v21, v22,
            v23, v24, v25, v26, v27, v28
        FROM transactions
        WHERE transaction_id = %s;
        """

        cursor.execute(query, (transaction_id,))
        transaction = cursor.fetchone()

        # -------------------------------------------------
        # CHECK TRANSACTION
        # -------------------------------------------------

        if transaction is None:
            raise HTTPException(
                status_code=404,
                detail=f"Transaction ID {transaction_id} not found"
            )

        # -------------------------------------------------
        # PREPARE ML DATA
        # -------------------------------------------------
        data = {
            "Time": transaction[0],
            "Amount": transaction[1],
            "V1": transaction[2],
            "V2": transaction[3],
            "V3": transaction[4],
            "V4": transaction[5],
            "V5": transaction[6],
            "V6": transaction[7],
            "V7": transaction[8],
            "V8": transaction[9],
            "V9": transaction[10],
            "V10": transaction[11],
            "V11": transaction[12],
            "V12": transaction[13],
            "V13": transaction[14],
            "V14": transaction[15],
            "V15": transaction[16],
            "V16": transaction[17],
            "V17": transaction[18],
            "V18": transaction[19],
            "V19": transaction[20],
            "V20": transaction[21],
            "V21": transaction[22],
            "V22": transaction[23],
            "V23": transaction[24],
            "V24": transaction[25],
            "V25": transaction[26],
            "V26": transaction[27],
            "V27": transaction[28],
            "V28": transaction[29]
        }

        # -------------------------------------------------
        # CREATE DATAFRAME FOR ML MODEL
        # -------------------------------------------------

        input_df = pd.DataFrame(
            [data],
            columns=features
        )

        input_df = input_df.apply(pd.to_numeric)

        # -------------------------------------------------
        # XGBOOST PREDICTION
        # -------------------------------------------------

        probability = float(
            model.predict_proba(input_df)[0][1]
        )

        threshold = 0.50

        prediction = int(
            probability >= threshold
        )

        result = (
            "Fraud"
            if prediction == 1
            else "Legitimate"
        )
        # -------------------------------------------------
        # RISK LEVEL
        # -------------------------------------------------

        if probability >= 0.70:
            risk_level = "High"
        elif probability >= 0.30:
            risk_level = "Medium"
        else:
            risk_level = "Low"

        # -------------------------------------------------
        # SAVE PREDICTION TO DATABASE
        # -------------------------------------------------

        insert_query = """
        INSERT INTO fraud_predictions
        (
            transaction_id,
            fraud_probability,
            predicted_class,
            model_name,
            threshold
        )
        VALUES (%s, %s, %s, %s, %s)
        RETURNING prediction_id;
        """

        cursor.execute(
            insert_query,
            (
                transaction_id,
                probability,
                prediction,
                "XGBoost",
                threshold
            )
        )

        prediction_id = cursor.fetchone()[0]

        conn.commit()

        

        # -------------------------------------------------
        # LOG PREDICTION
        # -------------------------------------------------

        logger.info(
            "Prediction completed - transaction_id=%s, prediction=%s, "
            "probability=%.6f, risk_level=%s",
            transaction_id,
            prediction,
            probability,
            risk_level
        )

        # -------------------------------------------------
        # RETURN RESPONSE
        # -------------------------------------------------

        return {
            "prediction_id": prediction_id,
            "transaction_id": transaction_id,
            "prediction": prediction,
            "result": result,
            "fraud_probability": probability,
            "risk_level": risk_level,
            "threshold": threshold,
            "model": "XGBoost"
        }

    # =====================================================
    # ERROR HANDLING
    # =====================================================

    except HTTPException:
        raise

    except Exception as e:

        if conn:
            conn.rollback()

        logger.exception("Prediction request failed")

        raise HTTPException(
            status_code=500,
            detail="Internal server error"
        )

    

    finally:

        if cursor:
            cursor.close()

        if conn:
            conn.close()

    