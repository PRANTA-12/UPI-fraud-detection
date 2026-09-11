from fastapi.testclient import TestClient
from api.main import app


client = TestClient(app)


def test_root():
    response = client.get("/")

    assert response.status_code == 200
    assert response.json()["message"] == "UPI Fraud Detection API is running"


def test_health():
    response = client.get("/health")

    assert response.status_code == 200

    data = response.json()

    assert data["status"] == "healthy"
    assert data["model"] == "XGBoost"
    assert data["database"] == "PostgreSQL"


def test_predict_valid_transaction():
    response = client.post(
        "/predict",
        json={"transaction_id": 542}
    )

    assert response.status_code == 200

    data = response.json()

    assert data["transaction_id"] == 542
    assert data["prediction"] in [0, 1]
    assert data["result"] in ["Fraud", "Legitimate"]
    assert 0 <= data["fraud_probability"] <= 1
    assert data["risk_level"] in ["High", "Medium", "Low"]
    assert data["threshold"] == 0.50
    assert data["model"] == "XGBoost"
    

def test_predict_invalid_transaction_id():
    response = client.post(
        "/predict",
        json={"transaction_id": -1}
    )

    assert response.status_code == 422


def test_predict_transaction_not_found():
    response = client.post(
        "/predict",
        json={"transaction_id": 999999999}
    )

    assert response.status_code == 404