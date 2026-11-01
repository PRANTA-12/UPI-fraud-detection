# Real-time pipeline

```
producer ──XADD──► Redis Stream ──XREADGROUP──► consumer(s) ──► PostgreSQL (fraud_predictions)
                       │                              │──► Redis Pub/Sub ──► API /ws/live ──► dashboard
                       └─ dead-letter stream ◄────────┘ (poison or retries exhausted)
```

## Event contract (what any source must emit)
`XADD transactions_stream * data <json> enqueued_at_ms <epoch-ms>` where `data` contains
`transaction_id, transaction_time, amount, v1…v28` (+ optional `actual_class`). Unknown transactions are inserted automatically,
so a native UPI source does not need to pre-populate `transactions`. Swap `streaming/producer.py` for your source; nothing downstream changes.
(For native data, replace `core/features.py` and retrain — the contract is the feature function, not the column names.)

## Producer (`streaming/producer.py`) — demo stand-in
Replays rows from `transactions` in id order; the cursor lives in Redis (`producer:cursor`) so restarts resume. Delay is random between
`PRODUCER_MIN_DELAY_MS` and `PRODUCER_MAX_DELAY_MS`. `PRODUCER_FRAUD_BOOST` (default 0.03) occasionally replays a not-yet-sent *real labelled fraud*
row so demos show alerts (pure replay would show one every ~10 minutes). It inflates the live fraud share; set `0` for faithful rates.
If Redis state is lost the producer restarts from id 1 — harmless, because the consumer skips already-scored transactions (idempotency).

## Consumer (`streaming/consumer.py`)
| Concern | Behaviour |
|---|---|
| Parallelism | One consumer group; run `--scale consumer=N`. `CONSUMER_NAME` defaults to the hostname. |
| Duplicates / idempotency | Unique `idempotency_key = "<txn>:<model_version>"`; conflicts are skipped and **do not publish a second alert**. |
| Delivery | At-least-once: `XACK` only after the DB commit. |
| Transient failure | 3 in-process attempts, then the message stays pending; `XAUTOCLAIM` re-delivers after `RETRY_IDLE_MS`. |
| Retry limit | After `MAX_RETRIES` deliveries → dead-letter stream with the error and delivery count. |
| Poison messages | Bad JSON / missing fields → dead-letter immediately. |
| Latency | `latency_ms` = enqueue → prediction ready (just before commit); `inference_ms` = model time only. Backlogs show up as latency, as they should. |
| Model rollout | Re-reads `models/registry.json` every 30 s; a new active version is used without restart (idempotency keys are per version). |
| Observability | Heartbeat hash `hb:consumer:<name>` (20 s TTL) with processed/failed/duplicate/dead counters. |

## Alerts and the WebSocket
Every scored transaction is published to `fraud_alerts` (JSON, `type: "prediction"`, `alert: true` when flagged). The API holds **one** subscription and fans
out to connected browsers at `/ws/live?token=<JWT>` (invalid token → close 4401). The dashboard shows toast notifications according to the admin's alert settings.

## Operating it
```bash
curl localhost:8000/stream/status                         # stream length, groups, DLQ size (original endpoint)
docker compose up -d --scale consumer=3                   # more throughput
docker compose exec redis redis-cli -a "$REDIS_PASSWORD" XRANGE transactions_stream:dlq - +     # inspect failures
```
The System Health page shows live consumers, lag, pending, DLQ size and recent DLQ errors.

## Known simplifications
No automatic DLQ replay or alerting on DLQ growth (visible on the System page, no pager). A single Redis instance is a single point of failure.
Pub/Sub is fire-and-forget (a browser that is offline misses events; history is in PostgreSQL and the Live page seeds from it).
