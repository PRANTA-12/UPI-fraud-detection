# UPI Fraud Detection

An end-to-end fraud detection prototype using Machine Learning,
PostgreSQL and FastAPI.

## Tech Stack

- Python
- Pandas
- NumPy
- Scikit-learn
- XGBoost
- PostgreSQL
- FastAPI
- Swagger
- Git/GitHub

## Machine Learning

Model: XGBoost

Fraud Precision: 94.25%
Fraud Recall: 83.67%
F1 Score: 88.65%
ROC-AUC: 97.70%
PR-AUC: 88.59%

## API

POST /predict

Example request:

{
  "transaction_id": 542
}

The API:
1. Fetches transaction data from PostgreSQL
2. Loads the trained ML model
3. Generates fraud probability
4. Applies a 0.50 threshold
5. Stores the prediction in PostgreSQL
6. Returns the prediction through FastAPI

## Database

PostgreSQL database:
upi_fraud_db

Tables:
- transactions
- fraud_predictions

## Run Locally

Create virtual environment

Install dependencies

Configure .env

Start FastAPI

Open Swagger:
http://127.0.0.1:8000/docs