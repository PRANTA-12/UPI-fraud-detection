# Phase 1 — Technical audit of the original project

Scope: the files that were provided (`create_tables.py`, `load_data.py`, `import_to_neon.py`, `test_db.py`, `Dockerfile`,
`docker-compose.yml`, `requirements.txt`, `.env`, README, REALTIME.md). **The original `api/main.py`, `streaming/*.py`, `static/live.html`
and `models/*.pkl` were never provided**, so they were *not* audited; the new versions were rebuilt from the behaviour documented in your README/REALTIME.md
(same endpoints, env vars, table names, `XGBoost-Streaming` model name, 422/404 semantics). The old pickled model was replaced by a newly trained, versioned model.

| # | Finding | Severity | Resolution |
|---|---|---|---|
| 1 | Dockerfile started uvicorn on `${PORT:-10000}` while compose published `8000` → API unreachable in Docker | High | Port 8000 default + health check |
| 2 | `import_to_neon.py` inserted explicit IDs without advancing the `SERIAL` sequence → later inserts collide | High | Shared loader calls `setval`; test-covered |
| 3 | `load_data.py` not idempotent (double run duplicates 284,807 rows); hard-coded totals | High | Idempotent COPY loader, refuses partial/duplicate loads |
| 4 | `test_db.py` contained a plaintext DB password | High | Removed; **rotate it and purge git history if it was ever pushed** |
| 5 | `create_tables.py` hard-coded host/user/password, ignored env | Med | Replaced by Alembic migrations (wrapper kept) |
| 6 | `.env` had a `DB_PORT` that may be the host port (5433) rather than the container port (5432) | Med | Compose pins internal 5432; `DB_HOST_PORT` for publishing |
| 7 | No indexes besides PKs; no FK index; no idempotency constraint; no model version / latency / status columns | Med | Migration `0002` (additive, back-fills legacy rows as `model_version='legacy'`) |
| 8 | No authentication; `/ws/live` open; Redis unauthenticated and published on all interfaces; containers run as root | High | JWT + RBAC, WS token, Redis password, `127.0.0.1` binds, non-root + hardened containers |
| 9 | `requirements.txt` unpinned; missing libs for auth, migrations, explainability | Med | Pinned runtime / ml / dev files |
| 10 | README metrics not reproducible; likely random split with duplicates (leakage) | Med | New temporal protocol; honest, lower numbers documented |
| 11 | README claims “automated API tests” but none were provided | Low | 69 tests written |
| 12 | Fixed `CONSUMER_NAME: consumer-1` in compose prevents scaling | Low | Hostname-based names |
| 13 | Dockerfile had a UTF-8 BOM and copied no `scripts/`/migrations | Low | Rewritten |
| 14 | Dataset has no real timestamps → time trends would be fabricated | Design | Time axes use prediction *processing time*; hour pattern labelled “hours since dataset start” |

| 15 | Original model scores ≈ 99 % precision on *every* time slice, incl. data a leakage-free model never saw → trained on the full dataset; its README metrics and every dashboard number computed on this dataset are in-sample | High | `legacy` kept as a comparison version with **no** metrics; new model evaluated temporally; dashboard shows held-out figures separately |
| 16 | Original `main.py` (provided later) used a pickled model (version-fragile; XGBoost warns on load), `threshold=0.50`, `/health` returning 503 on DB failure | Med | Native-JSON models; response shapes of `/`, `/health`, `/stream/status` restored and covered by tests |

Originally not assessed (files absent at the time; `main.py`/`live.html`/models were provided afterwards and are covered by rows 15–16): original API code, streaming code, dashboard, model preprocessing.
