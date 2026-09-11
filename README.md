# UPI Fraud Detection

An end-to-end fraud detection prototype using Machine Learning,
PostgreSQL, and FastAPI.

## Tech Stack

- Python
- Pandas
- NumPy
- Scikit-learn
- XGBoost
- PostgreSQL
- FastAPI
- Swagger
- Pytest
- Git/GitHub

## Machine Learning

**Model:** XGBoost

| Metric | Score |
|---|---:|
| Fraud Precision | 94.25% |
| Fraud Recall | 83.67% |
| F1 Score | 88.65% |
| ROC-AUC | 97.70% |
| PR-AUC | 88.59% |

> Accuracy is not used as the primary evaluation metric because the dataset is highly imbalanced.

## API

### POST /predict

The `/predict` endpoint accepts a transaction ID, retrieves the corresponding
transaction from PostgreSQL, runs the XGBoost fraud detection model, calculates
fraud probability, determines the risk level, and stores the prediction in the
database.

### Request

```json
{
  "transaction_id": 542
}

{
  "prediction_id": 10,
  "transaction_id": 542,
  "prediction": 1,
  "result": "Fraud",
  "fraud_probability": 0.9893,
  "risk_level": "High",
  "threshold": 0.5,
  "model": "XGBoost"
}