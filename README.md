# UPI Fraud Detection

An end-to-end fraud detection prototype built using Machine Learning, PostgreSQL, FastAPI, Swagger, and Docker.

The system retrieves transaction data from PostgreSQL, applies a trained XGBoost classification model, calculates fraud probability, assigns a risk level, and stores the prediction result back into PostgreSQL.

> **Dataset Note:** This project uses the widely used Credit Card Fraud Detection dataset with `Time`, `V1–V28`, `Amount`, and `Class` features. It is adapted as a fraud-detection prototype for a UPI-style transaction workflow rather than representing native UPI transaction data.

---

## Project Architecture

```text
                    Client
                      │
                      ▼
               Swagger / API
                      │
                      ▼
                  FastAPI
                      │
          ┌───────────┴───────────┐
          │                       │
          ▼                       ▼
     PostgreSQL              XGBoost Model
     Transactions                  │
          │                        │
          └───────────┬────────────┘
                      ▼
               Fraud Probability
                      │
                      ▼
                  Risk Level
                      │
                      ▼
               PostgreSQL
              fraud_predictions
```

---

## Tech Stack

### Programming & Data Science

- Python
- Pandas
- NumPy
- Scikit-learn
- XGBoost
- Joblib

### Backend & Database

- FastAPI
- Uvicorn
- PostgreSQL
- Psycopg2

### API Testing

- Swagger UI
- Pytest

### Deployment & Version Control

- Docker
- Docker Compose
- Git
- GitHub

---

## Machine Learning

### Model

**XGBoost Classifier**

The dataset is highly imbalanced, so precision, recall, F1-score, ROC-AUC, and PR-AUC are more useful than accuracy alone.

### Model Performance

| Metric | Score |
|---|---:|
| Fraud Precision | 94.25% |
| Fraud Recall | 83.67% |
| F1 Score | 88.65% |
| ROC-AUC | 97.70% |
| PR-AUC | 88.59% |

> Accuracy is not used as the primary evaluation metric because the dataset is highly imbalanced.

### Classification Threshold

The current prediction threshold is:

```text
0.50
```

### Risk Levels

Risk levels are assigned using fraud probability:

| Fraud Probability | Risk Level |
|---:|---|
| < 0.30 | Low |
| 0.30 – < 0.70 | Medium |
| >= 0.70 | High |

---

## Dataset

The project uses the Credit Card Fraud Detection dataset.

### Features

```text
Time
V1 - V28
Amount
Class
```

### Dataset Information

| Information | Value |
|---|---:|
| Total Transactions | 284,807 |
| Legitimate Transactions | 284,315 |
| Fraudulent Transactions | 492 |
| Fraud Rate | Approximately 0.17% |
| Total Features | 30 |
| Target Variable | `Class` |

### Target Variable

```text
0 = Legitimate
1 = Fraud
```

> The `Time` column represents elapsed seconds in the original dataset. It is transformed into an hour-of-day feature for exploratory analysis.

---

## API

The backend is built using FastAPI.

### Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/` | API information |
| GET | `/health` | Health check |
| POST | `/predict` | Predict fraud for a transaction |

### Swagger Documentation

The API can be tested using Swagger UI:

```text
http://127.0.0.1:8000/docs
```

### Prediction Request

```json
{
  "transaction_id": 542
}
```

### Fraud Prediction Example

```json
{
  "prediction_id": 17,
  "transaction_id": 542,
  "prediction": 1,
  "result": "Fraud",
  "fraud_probability": 0.989385187625885,
  "risk_level": "High",
  "threshold": 0.5,
  "model": "XGBoost"
}
```

### Legitimate Prediction Example

```json
{
  "transaction_id": 3,
  "prediction": 0,
  "result": "Legitimate",
  "fraud_probability": 0.00004887185787083581,
  "risk_level": "Low",
  "threshold": 0.5,
  "model": "XGBoost"
}
```

### API Validation

The API validates transaction IDs.

For example:

```json
{
  "transaction_id": -1
}
```

Returns HTTP `422` because the transaction ID must be positive.

A nonexistent transaction such as:

```json
{
  "transaction_id": 999999999
}
```

Returns HTTP `404`.

Example response:

```json
{
  "detail": "Transaction ID 999999999 not found"
}
```

---

## Database

PostgreSQL is used to store transaction data and prediction results.

### `transactions`

Stores transaction records.

Main fields:

```text
transaction_id
transaction_time
amount
V1 - V28
actual_class
```

### `fraud_predictions`

Stores model prediction results.

Main fields:

```text
prediction_id
transaction_id
fraud_probability
predicted_class
model_name
threshold
prediction_time
```

---

## Docker

The application is containerized using Docker and Docker Compose.

### Architecture

```text
                 Docker Compose
                       │
              ┌────────┴────────┐
              │                 │
              ▼                 ▼
        PostgreSQL           FastAPI
                              │
                              ▼
                         XGBoost Model
```

### Start the Application

**PowerShell:**

```powershell
docker compose up -d
```

### Check Running Containers

```powershell
docker compose ps
```

### View API Logs

```powershell
docker compose logs api
```

### Stop the Application

```powershell
docker compose down
```

### Ports

```text
FastAPI       → 8000
PostgreSQL    → 5433
```

---

## Project Structure

```text
UPI-fraud-detection/
│
├── api/
│   └── main.py
│
├── models/
│   ├── fraud_model.pkl
│   └── features.pkl
│
├── create_tables.py
├── load_data.py
├── test_db.py
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
├── .gitignore
├── requirements.txt
└── README.md
```

---

## Testing

The project has been tested using Swagger UI and automated API tests.

### Verified Scenarios

- API health check → `200 OK`
- Legitimate transaction prediction
- Fraudulent transaction prediction
- Invalid transaction ID → `422`
- Nonexistent transaction → `404`
- Prediction stored in PostgreSQL
- FastAPI running inside Docker
- PostgreSQL running inside Docker
- XGBoost model loaded successfully

---

## System Workflow

```text
Transaction ID
      │
      ▼
   FastAPI
      │
      ▼
 PostgreSQL
      │
      ▼
Transaction Features
      │
      ▼
 XGBoost Model
      │
      ▼
Fraud Probability
      │
      ▼
 Risk Classification
      │
      ▼
 PostgreSQL
      │
      ▼
  API Response
```

---

## Key Features

- Machine Learning based fraud detection
- XGBoost classification
- Fraud probability scoring
- Risk-level classification
- PostgreSQL transaction storage
- Prediction history storage
- FastAPI REST API
- Swagger API documentation
- Input validation
- Error handling
- Automated API testing
- Docker containerization
- Docker Compose deployment
- Git and GitHub version control

---

## Limitations

- The dataset is a credit card fraud dataset rather than native UPI transaction data.
- The current model is a prototype and is not production-ready.
- The fraud threshold of `0.50` is a baseline and would require business-level tuning in a real fraud detection system.
- Real-world UPI fraud detection would require additional transaction, device, user, merchant, velocity, and behavioral features.

---

## Future Improvements

- Real-time transaction streaming
- User behavioral features
- Device and location features
- Transaction velocity features
- Advanced feature engineering
- Threshold optimization
- Model monitoring
- MLflow experiment tracking
- Explainable AI using SHAP
- AWS cloud deployment
- Authentication and authorization
- Real-time fraud alerts
- Production monitoring dashboard

---

## Author

**Pranta Pratap Ghosh**

B.Tech CSE Student

Aspiring Data Scientist / ML Engineer