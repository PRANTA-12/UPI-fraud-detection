from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import pandas as pd
import joblib
import psycopg2
from pathlib import Path
from dotenv import load_dotenv
import os
import logging

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
    description="Fraud detection API using XGBoost and PostgreSQL",
    version="1.0"
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


# =========================================================
# DATABASE CONNECTION
# =========================================================

def get_connection():
    return psycopg2.connect(**DB_CONFIG)


# =========================================================
# REQUEST MODEL
# =========================================================

class TransactionRequest(BaseModel):
    transaction_id: int = Field(
        ...,
        gt=0,
        description="Positive transaction ID"
    )


# =========================================================
# RESPONSE MODEL
# =========================================================

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
        "message": "UPI Fraud Detection API is running"
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
# PREDICT ENDPOINT
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
        