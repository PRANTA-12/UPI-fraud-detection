# API reference

Interactive docs: `/docs` (Swagger) · `/redoc`. All JSON. Errors: `{"detail": …, "code": "…", "request_id": "…"}`.
Auth: `POST /auth/login` → `Authorization: Bearer <token>`. Roles: viewer < analyst < admin.

## Original endpoints (preserved)
| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/` | public* | API info |
| GET | `/health` | public* | `{"status","database"}` |
| POST | `/predict` | public* (analyst if `LEGACY_ENDPOINTS_PUBLIC=false`) | body `{"transaction_id": int>0}`; 422 invalid, 404 unknown; rate-limited 60/min. Response adds `model_version`, `latency_ms` |
| GET | `/stream/status` | public* | stream length, groups, DLQ size |
| WS | `/ws/live?token=` | JWT | `hello`, `pong`, `prediction` messages |

\*public unless `LEGACY_ENDPOINTS_PUBLIC=false`.

## New endpoints (viewer unless noted)
| Group | Endpoint | Purpose |
|---|---|---|
| Auth | `POST /auth/login` (10/min/IP) · `GET /auth/me` | token, identity |
| Dashboard | `GET /dashboard/kpis` · `/trends?bucket=minute|hour|day&window_hours=` · `/risk-distribution` · `/recent-suspicious` | executive metrics |
| Transactions | `GET /transactions` (`page,page_size≤100,q,risk,predicted,actual,model_version,min_amount,max_amount,sort,order,date_from,date_to`) | paginated, filtered, sorted history |
| | `GET /transactions/{id}` · `/{id}/explain?version=&top=` · `/{id}/compare` | investigation, TreeSHAP, version comparison |
| Analytics | `GET /analytics/summary` · `/hourly` · `/amount-distribution` · `/probability-distribution` · `/high-risk-patterns` | all accept `date_from/date_to` |
| Model | `GET /model/info` · `/metrics` · `/importance` · `/history` · `/prediction-distribution` · `/drift` | artifacts + live monitoring |
| System | `GET /system/health` | component status, stream, DLQ, throughput, API latency |
| Settings | `GET /settings` · `PUT /settings` (**admin**) · `GET /admin/audit` (**admin**) | thresholds, refresh, alerts; audit trail |

Date filters use prediction processing time (`processed_at`).
