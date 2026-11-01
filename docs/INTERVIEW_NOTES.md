# Interview notes — UPI SENTINEL

## 30-second pitch
“A real-time fraud scoring platform: transactions flow through Redis Streams to horizontally scalable consumers that score them with a versioned XGBoost
model, persist idempotent predictions in PostgreSQL, push alerts over WebSockets, and surface everything in a monitoring dashboard with SHAP explanations.
I trained on a public credit-card dataset as a stand-in for UPI data and I'm explicit about that.”

## Decisions you can defend
* **Redis Streams over Pub/Sub for ingestion** — consumer groups, replay, acknowledgements; Pub/Sub only for fire-and-forget fan-out to browsers.
* **Idempotency in the database** (unique key `txn:model_version`) rather than in memory — survives restarts, multiple consumers, and producer replays.
* **At-least-once + idempotent writes** instead of chasing exactly-once.
* **Temporal split + dedupe** — fraud models are used on future data; random splits with duplicates inflate scores. My honest PR-AUC is 78.6 %, not the 88.6 % I started with.
* **PR-AUC & recall/precision, not accuracy** (0.17 % fraud). Threshold chosen on out-of-fold train predictions (F2 s.t. precision ≥ 0.75), never on test.
* **Class weights over SMOTE** — no synthetic rows leaking across CV folds.
* **One feature function** shared by train/API/consumer → no train/serve skew.
* **Native `pred_contribs`** for serving-time TreeSHAP (no heavy `shap` import in the API); verified equal to `shap.TreeExplainer`.
* **Additive Alembic migrations** + `latest_predictions` view; legacy rows kept as `model_version='legacy'`.
* **Vanilla ES-module dashboard** (no build step, XSS-safe `textContent` rendering); would move to React/TypeScript if it grew.

## Questions to expect, and honest answers
* *“How good is the model?”* 76.7 % precision / 75.7 % recall on a temporal hold-out with 74 frauds — wide error bars; tuning didn't beat default XGBoost; RF is statistically tied.
* *“Is it production ready?”* No: public data, no real labels feedback loop, no drift baseline from live traffic, JWT in sessionStorage, single Redis, Docker stack not load-tested.
* *“What happens if the consumer crashes mid-message?”* Message stays pending → `XAUTOCLAIM` after idle time → retried; after `MAX_RETRIES` → DLQ. DB unique key prevents double writes.
* *“How would you scale it?”* More consumers (group), partition/rollup tables, materialised KPI views, read replica for the dashboard, Redis Cluster/Kafka at larger volume.
* *“What would you do with real UPI data?”* New feature function (velocity, device, VPA history), delayed-label evaluation, cost-based threshold, drift monitoring against a real baseline, shadow-mode deployment.
* *“Why do latency numbers look high sometimes?”* They include queue wait; after a consumer outage the backlog shows up as latency (observed ~13 s average during catch-up in testing, ~39 ms steady-state).

## The strongest story (be ready to tell it)
“My original model reported 94 % precision. When I rebuilt the evaluation properly — dedupe, temporal split, threshold chosen out-of-fold — the honest number was ~77 %. Then I scored my old model on data my new model never saw
and it got 100 % precision, which told me it was trained on the whole dataset. I imported it as a `legacy` version, proved the conversion was exact against the 4,571 predictions stored in my database, and made the dashboard report
held-out performance separately so the demo can't flatter itself.” It shows leakage awareness, versioning, and honesty about metrics.

## Numbers you measured (dev sandbox, 1 CPU core)
Steady-state end-to-end latency ≈ 39 ms avg / 54 ms p95, inference ≈ 8 ms, ≈ 2.7 txn/s at the configured producer pace (not a capacity limit). 70 automated tests; mutation checks confirmed tests fail when idempotency, retry limit or risk bands are broken.
