# Real-Time Streaming Extension

This adds a real-time scoring pipeline alongside your existing on-demand
`/predict` endpoint. Nothing in your original API, DB schema, or Docker
setup was removed — this is additive.

## New architecture

```
                 ┌───────────────┐
                 │   producer     │  replays transactions table
                 │ (simulator)    │  onto a Redis Stream, one at a
                 └───────┬────────┘  time, at irregular intervals
                         │
                         ▼
                 Redis Stream
                 "transactions_stream"
                         │
                         ▼
                 ┌───────────────┐
                 │   consumer     │  scores each transaction with
                 │ (real-time)    │  the same XGBoost model as /predict
                 └───────┬────────┘
                         │
             ┌───────────┴────────────┐
             ▼                        ▼
      PostgreSQL                Redis Pub/Sub
   fraud_predictions            "fraud_alerts"
                                       │
                                       ▼
                                 FastAPI (/ws/live)
                                       │
                                       ▼
                              Browser (static/live.html)
```

- **producer** (`streaming/producer.py`) — stands in for a real transaction
  source. It replays your existing `transactions` table row by row so you
  get a live-feeling feed without needing a real UPI switch connected.
  **This is the one piece you'll eventually delete and replace** with
  whatever actually emits transactions in your environment (a webhook, a
  Kafka topic bridged in from a payment gateway, etc). It only needs to
  push the same JSON shape onto the stream — everything downstream is
  unaffected by that swap.
- **Redis Stream** — the message broker. Durable, ordered, supports
  consumer groups (so you can run multiple consumers and each transaction
  is still scored exactly once), and needs zero extra infrastructure
  beyond the `redis` container already in `docker-compose.yml`.
- **consumer** (`streaming/consumer.py`) — the actual real-time scorer.
  Pulls from the stream, scores with your existing model, writes to
  `fraud_predictions` (tagged `model_name = "XGBoost-Streaming"` so you can
  tell real-time predictions apart from ones made via `/predict`), and
  publishes the result to a pub/sub channel. Failed messages go to a
  dead-letter stream (`transactions_stream:dlq`) instead of blocking the
  pipeline.
- **`/ws/live`** — a WebSocket endpoint on the existing FastAPI app.
  Subscribes to the pub/sub channel once and fans every scored transaction
  out to all connected clients.
- **`static/live.html`** — a minimal dashboard, no build step, that
  connects to `/ws/live` and shows predictions arriving in real time,
  color-coded by risk level.
- **`/stream/status`** — quick observability endpoint: current stream
  length and consumer group info, so you can see if the consumer is
  keeping up or falling behind.

## Running it

```powershell
docker compose up -d --build
```

This now starts five containers: `db`, `redis`, `api`, `consumer`,
`producer`. The producer starts feeding transactions immediately.

Open the live feed:

```text
http://127.0.0.1:8000/static/live.html
```

You should see rows appearing every ~0.2–1.5s (configurable via
`PRODUCER_MIN_DELAY_MS` / `PRODUCER_MAX_DELAY_MS`), color-coded green
(Low), yellow (Medium), red (High).

Check pipeline health:

```text
http://127.0.0.1:8000/stream/status
```

Scale up consumers if the stream backs up:

```powershell
docker compose up -d --scale consumer=3
```

(drop `container_name` conflicts don't apply here — `consumer` has none,
by design, so it scales cleanly.)

## What still uses the old path

Your `/predict` endpoint is untouched — it still does on-demand,
pull-based scoring for a single `transaction_id` on request. That's still
useful (e.g. someone manually re-checking a specific transaction from a
support ticket) and doesn't conflict with the streaming path; they just
both write to the same `fraud_predictions` table with different
`model_name` values so you can filter by source.

## Known simplifications (call these out if this goes further)

- The producer replaying historical data is a stand-in for a real feed —
  swap it out first when you have an actual transaction source.
- The consumer's error handling routes failures to a DLQ stream but
  doesn't retry or alert on DLQ growth yet.
- There's no authentication on `/ws/live` — fine for a local demo, not for
  anything exposed publicly.
- This is still a single-model, static-threshold system. The MLOps
  (MLflow model registry) and monitoring/drift-detection layers we
  discussed as next steps aren't in this pass — say the word and we'll
  build those next, on top of this pipeline.
