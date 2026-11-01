# UPI SENTINEL — Real-Time Fraud Detection & Risk Intelligence

An end-to-end fraud-detection platform: versioned XGBoost model with SHAP explanations, a Redis-Streams
real-time scoring pipeline, a FastAPI backend with JWT/RBAC, PostgreSQL with migrations, and a seven-page
dark-theme monitoring dashboard.

> **Dataset disclaimer.** The model is trained on the public *Credit Card Fraud Detection* dataset
> (284,807 transactions, 492 frauds, anonymised `V1–V28`). It is used as a **research prototype for a UPI-style
> workflow**. It contains **no genuine UPI data**, and nothing here should be presented as validated for production.
> The ingestion contract (`streaming/common.py::encode_event`) is source-agnostic so native UPI events can replace the replay producer.

## Architecture

```
 Transaction source                                   ┌───────────────────────────────┐
 (replay producer today;  ──►  Redis Stream  ──►  Consumer(s)  ──►  PostgreSQL        │
  UPI switch/webhook later)    transactions_stream   │ features → XGBoost → risk band │ fraud_predictions
        │                              │ consumer group (N replicas, each msg once)   │ (idempotent, versioned, latency)
        │                              ▼                                              └───────────────────────────────┘
        │                       dead-letter stream                       │
        │                       (poison / max retries)                   ▼
        │                                                       Redis Pub/Sub "fraud_alerts"
        │                                                                │
        ▼                                                                ▼
   heartbeats ───────────────────────►  FastAPI  ◄── PostgreSQL aggregates (KPIs, analytics, investigation)
                                          │  REST (JWT + roles)   │  WebSocket /ws/live (token)
                                          ▼                       ▼
                                  Dashboard SPA  (static/, Chart.js vendored, no build step)
```

| Layer | Technology | Where |
|---|---|---|
| Model & training | XGBoost, scikit-learn, SHAP, MLflow | `ml/`, `models/` |
| Streaming | Redis Streams (+ consumer groups), Pub/Sub | `streaming/` |
| API | FastAPI, Pydantic v2, JWT, bcrypt | `api/`, `core/` |
| Database | PostgreSQL 16, Alembic | `migrations/` |
| Dashboard | Vanilla ES modules + Chart.js | `static/` |
| Ops | Docker Compose, health checks, CI | `Dockerfile`, `docker-compose.yml` |

## Quick start (Docker)

```bash
git clone <your-repo> && cd upi-sentinel
python scripts/generate_env.py                 # creates .env with random secrets, prints the admin password
# put creditcard.csv (Kaggle "Credit Card Fraud Detection") in this folder, then:
docker compose up -d --build                   # db, redis, migrate, api, consumer, producer
docker compose --profile tools run --rm loader # one-time, idempotent: loads 284,807 rows
```

Open **http://localhost:8000/app/** and sign in as `admin` with the printed password.
API docs: http://localhost:8000/docs. Scale consumers: `docker compose up -d --scale consumer=3`.

> The loader and producer need the data loaded first. Re-running the loader is a no-op.
> The original `http://localhost:8000/static/live.html` URL redirects to the new Live Monitoring page.

### Without Docker
```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-ml.txt -r requirements-dev.txt
cp .env.example .env   # set DB_HOST=localhost, REDIS_HOST=localhost, secrets, ...
alembic upgrade head && python load_data.py --csv creditcard.csv
uvicorn api.main:app --reload   # + in other shells:  python -m streaming.consumer / python -m streaming.producer
```

## Machine learning

Train (≈6 min on one CPU core): `python -m ml.train --csv creditcard.csv` → writes `models/versions/vN/`, updates
`models/registry.json` (newest becomes active; edit the file to roll back) and logs to MLflow.

**Leakage controls:** 1,081 exact duplicate rows removed *before* splitting · **temporal split** (first 80 % of time = train,
last 20 % = untouched test) · all CV/tuning/threshold selection on the train period only · no resampling (class weights /
`scale_pos_weight`, so nothing synthetic crosses folds) · scaling for logistic regression lives inside a pipeline.

**Features** (`core/features.py`, shared by training, API and consumer so there is no train/serve skew):
`V1–V28`, `log_amount`, `is_round_amount`, cyclic `hour_sin/hour_cos`
(*hour = hours since dataset start mod 24 — the dataset has no wall-clock time*).

**Model comparison** (5-fold stratified CV on the training period; test = one evaluation on the hold-out at threshold 0.5):

| Model | CV PR-AUC | CV recall | CV precision | Test PR-AUC | Test recall | Test precision |
|---|---:|---:|---:|---:|---:|---:|
| Logistic Regression | 71.1 % ± 2.7 | 90.5 % | 6.4 % | 75.3 % | 91.9 % | 2.3 % |
| Random Forest | 82.3 % ± 3.2 | 77.5 % | 87.4 % | 79.9 % | 71.6 % | 98.1 % |
| XGBoost (defaults) | 85.5 % ± 3.3 | 84.2 % | 89.4 % | 79.2 % | 75.7 % | 81.2 % |
| **XGBoost (tuned, deployed)** | 85.3 % ± 3.0 | 83.7 % | 88.4 % | 78.6 % | 75.7 % | 78.9 % |

**Deployed model `v1` on the held-out test set** at its tuned threshold (0.395: *maximise F2 on out-of-fold train
predictions subject to precision ≥ 0.75*):

| Precision | Recall | F1 | ROC-AUC | PR-AUC | Confusion (TN / FP / FN / TP) |
|---:|---:|---:|---:|---:|---|
| 76.7 % | 75.7 % | 76.2 % | 98.3 % | 78.6 % | 56,655 / 17 / 18 / 56 |

**Read these numbers honestly.**
* They are **lower than the 94 % precision / 88.6 % PR-AUC in the previous README**. Those figures cannot be reproduced from the
  code I had; a random split that keeps duplicate rows (and ignores time) is the usual cause of that gap. The numbers above are from a stricter protocol.
* The test period contains only **74 fraud cases**, so each metric has wide uncertainty. Differences between RF and XGBoost
  are within noise, and hyper-parameter tuning did **not** measurably improve on the default XGBoost. XGBoost is deployed because it is the
  required real-time model, balances precision and recall, and has exact TreeSHAP explanations.
* Threshold optimisation did not beat 0.5 on this small test set (F1 77.2 % at 0.5 vs 76.2 %). It is selected from out-of-fold data on principle, not hindsight.

**Explainability.** Per-transaction contributions use XGBoost's native `pred_contribs` (exact TreeSHAP). Training verifies it equals
`shap.TreeExplainer` (max difference recorded in `metadata.json`). Features are anonymised PCA components, so explanations name `V14`, not “merchant risk”.

**Risk bands** (unchanged defaults, now admin-configurable): `< 0.30` Low · `0.30–<0.70` Medium · `≥ 0.70` High.
The fraud/not-fraud decision uses the model's own threshold; risk bands are display bands.

## Real-time pipeline guarantees
Consumer groups (N replicas, each message handled once) · **idempotent** `INSERT … ON CONFLICT (idempotency_key)` with key `txn:model_version` ·
**at-least-once** (ack only after commit) · **bounded retries** (`MAX_RETRIES`, re-claim via `XAUTOCLAIM`) · **dead-letter stream** (poison immediately, others after retries) ·
measured **latency** (`latency_ms` enqueue→scored, `inference_ms` model only) · heartbeats for monitoring. Details: [REALTIME.md](REALTIME.md).

## Dashboard (http://localhost:8000/app/)
1 Executive Overview · 2 Live Transaction Monitoring · 3 Fraud Intelligence Analytics · 4 Transaction Investigation Center ·
5 AI Model Intelligence · 6 System Health · 7 Settings. “Predicted” figures (model output) are visually separated from “Ground truth” (replayed labels).
Every number comes from a SQL aggregate, a model artifact or a measured runtime value; empty/loading/error states are explicit.
Date filters apply to **prediction processing time** (the dataset has no real transaction timestamps).

## Security
bcrypt password hashing · JWT (HS256, 60 min) · roles `viewer < analyst < admin` · login rate-limit (Redis) and `/predict` limit · parameterised SQL only,
whitelisted sort columns · WebSocket requires a valid token (close code 4401) · CORS allow-list · security headers · errors never leak internals (request-id correlated) ·
audit log (logins, settings changes, predictions) · secrets only from environment, `.env` git-ignored · Docker: non-root user, `cap_drop: ALL`, read-only filesystem, `no-new-privileges`, DB/Redis bound to `127.0.0.1`, Redis password.
`APP_ENV=production` refuses to start with `AUTH_REQUIRED=false` or a weak `JWT_SECRET`.
**Original endpoints** (`/`, `/health`, `/stream/status`, `POST /predict`) stay public by default for backward compatibility; set `LEGACY_ENDPOINTS_PUBLIC=false` to protect them.

## Testing
`pip install -r requirements-dev.txt && python -m pytest` — **69 tests**: unit (features, risk, config, security), model (scoring, exact SHAP), database
(migrations, constraints, idempotency, view), API (original contract, auth/RBAC, validation, pagination, errors), streaming (idempotency, DLQ, retries, multi-consumer, producer resume), WebSocket (auth, broadcast).
A throw-away PostgreSQL is started automatically (`pgserver`); Redis is `fakeredis`. CI: `.github/workflows/ci.yml`.

## Cloud deployment (outline — not executed in this repo's test environment)
1. **Managed PostgreSQL** (Neon / RDS): `DATABASE_URL=… alembic upgrade head`, then `python import_to_neon.py` (or `load_data.py --database-url`).
2. **Managed Redis** with password/TLS (Upstash / ElastiCache) → `REDIS_HOST/PORT/PASSWORD`.
3. Build the image once; run **api** (public, behind HTTPS so the dashboard uses `wss://`), **consumer** (≥ 2 replicas, private) and, for demos only, **producer**. Container platforms: Render, Fly.io, AWS ECS/Fargate, Cloud Run (needs always-on CPU for consumers).
4. Set `APP_ENV=production`, strong `JWT_SECRET`, `ADMIN_PASSWORD`, `CORS_ORIGINS=https://your-domain`, `LEGACY_ENDPOINTS_PUBLIC=false`. Create other users with `scripts/create_user.py`.
5. Replace the replay producer with your real source; keep the event shape from `encode_event`.

## Limitations (please read)
* Not real UPI data; prototype, **not production-ready**. No claim of fraud-catching performance on real payments.
* Test set has 74 frauds; metrics are noisy. No drift baseline from real traffic (PSI is shown but meaningless while the replay feeds training-distribution data; `PRODUCER_FRAUD_BOOST` inflates fraud share).
* Latency/throughput numbers describe this prototype on the machine it runs on.
* In-process API latency stats are per worker; JWT is stored in `sessionStorage` (XSS-sensitive); no refresh tokens / token revocation; HS256 shared secret.
* `latest_predictions` view is fine at this scale; at tens of millions of predictions use materialised rollups / partitioning.
* Docker files were validated syntactically and by running every component natively; **`docker compose up` itself was not executed** in the build environment.

## Project layout
```
api/        FastAPI app, routers (legacy, auth, dashboard, transactions, analytics, models, system, settings), WebSocket
core/       config, db pool, security, risk, features, model store, settings store, rate limit, metrics
streaming/  producer.py  consumer.py  common.py
ml/         train.py  mlflow_log.py
models/     registry.json + versions/v1/{model.json, metadata.json, metrics.json, importance.json, drift_reference.json}
migrations/ Alembic (0001 baseline = your original tables, 0002 additive upgrade)
static/     dashboard (index.html, css/, js/, js/pages/, vendor/chart.umd.js)
scripts/    generate_env.py  create_user.py  healthcheck_*.py
tests/      69 tests        docs/  AUDIT.md  API.md  INTERVIEW_NOTES.md
```

Author: Pranta Pratap Ghosh
