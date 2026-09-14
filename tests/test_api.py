import psycopg2
from fastapi.testclient import TestClient

from api.main import app, DB_CONFIG


client = TestClient(app)


def test_health_check():
    response = client.get("/health")

    assert response.status_code == 200

    data = response.json()

    assert data["status"] == "healthy"
    assert data["model"] == "XGBoost"
    assert data["database"] == "PostgreSQL"


def test_legitimate_transaction():
    response = client.post(
        "/predict",
        json={"transaction_id": 3}
    )

    assert response.status_code == 200

    data = response.json()

    assert data["transaction_id"] == 3
    assert data["prediction"] == 0
    assert data["result"] == "Legitimate"
    assert 0 <= data["fraud_probability"] <= 1
    assert data["risk_level"] == "Low"
    assert data["threshold"] == 0.5
    assert data["model"] == "XGBoost"


def test_fraud_transaction():
    response = client.post(
        "/predict",
        json={"transaction_id": 542}
    )

    assert response.status_code == 200

    data = response.json()

    assert data["transaction_id"] == 542
    assert data["prediction"] == 1
    assert data["result"] == "Fraud"
    assert 0 <= data["fraud_probability"] <= 1
    assert data["risk_level"] == "High"
    assert data["threshold"] == 0.5
    assert data["model"] == "XGBoost"


def test_invalid_transaction_id():
    response = client.post(
        "/predict",
        json={"transaction_id": -1}
    )

    assert response.status_code == 422


def test_nonexistent_transaction():
    response = client.post(
        "/predict",
        json={"transaction_id": 999999999}
    )

    assert response.status_code == 404

    data = response.json()

    assert "not found" in data["detail"]


def test_prediction_stored_in_database():
    transaction_id = 542

    response = client.post(
        "/predict",
        json={"transaction_id": transaction_id}
    )

    assert response.status_code == 200

    prediction_data = response.json()

    prediction_id = prediction_data["prediction_id"]

    conn = psycopg2.connect(**DB_CONFIG)

    try:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT
                prediction_id,
                transaction_id,
                fraud_probability,
                predicted_class,
                model_name,
                threshold
            FROM fraud_predictions
            WHERE prediction_id = %s
            """,
            (prediction_id,)
        )

        row = cursor.fetchone()

        assert row is not None

        assert row[0] == prediction_id
        assert row[1] == transaction_id
        assert 0 <= row[2] <= 1
        assert row[3] == prediction_data["prediction"]
        assert row[4] == "XGBoost"
        assert row[5] == 0.5

    finally:
        cursor.close()
        conn.close()