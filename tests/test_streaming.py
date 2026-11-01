import json
import time

import fakeredis
import pytest

from core import db
from core.config import get_settings
from core.model_store import ModelStore
from streaming.common import encode_event, read_heartbeats
from streaming.consumer import Consumer
from core.repository import fetch_transaction

S = get_settings


@pytest.fixture()
def r(fake_server):
    return fakeredis.FakeStrictRedis(server=fake_server, decode_responses=True)


@pytest.fixture()
def consumer(env, r):
    s = S().model_copy(update={"max_retries": 2, "retry_idle_ms": 0, "consumer_name": "c-test"})
    c = Consumer(r, ModelStore("models"), s); c.ensure_group()
    return c


def publish(r, txn_id):
    r.xadd(S().stream_name, encode_event(fetch_transaction(txn_id)))


def test_scores_persists_and_publishes(consumer, r):
    ps = r.pubsub(); ps.subscribe(S().alert_channel); ps.get_message(timeout=1)
    publish(r, 900)
    assert consumer.step(block_ms=10) == 1
    row = db.query_one("SELECT * FROM fraud_predictions WHERE transaction_id = 900")
    assert row["source"] == "stream" and row["model_name"] == "XGBoost-Streaming" and row["predicted_class"] == 1
    assert row["latency_ms"] >= row["inference_ms"] >= 0 and row["enqueued_at"] is not None and row["idempotency_key"].startswith("900:")
    ev = json.loads(ps.get_message(timeout=1)["data"])
    assert ev["type"] == "prediction" and ev["alert"] is True and ev["risk_level"] == "High" and ev["transaction_id"] == 900
    assert ev["prediction"] == 1 and ev["model"] == "XGBoost-Streaming"      # fields the original live.html reads
    assert r.xpending(S().stream_name, S().consumer_group)["pending"] == 0       # acked after commit


def test_duplicate_messages_do_not_duplicate_predictions_or_alerts(consumer, r):
    ps = r.pubsub(); ps.subscribe(S().alert_channel); ps.get_message(timeout=1)
    publish(r, 7); publish(r, 7); publish(r, 7)
    consumer.step(block_ms=10)
    assert db.query_one("SELECT count(*) AS n FROM fraud_predictions WHERE transaction_id = 7")["n"] == 1
    assert consumer.processed == 1 and consumer.duplicates == 2
    msgs = [m for m in iter(lambda: ps.get_message(timeout=0.2), None) if m["type"] == "message"]
    assert len(msgs) == 1


@pytest.mark.parametrize("data", ["{broken json", json.dumps({"transaction_id": 5}), json.dumps({"transaction_id": "x"})])
def test_poison_messages_go_straight_to_dlq(consumer, r, data):
    r.xadd(S().stream_name, {"data": data})
    consumer.step(block_ms=10)
    dlq = r.xrange(S().dlq_stream_name)
    assert len(dlq) == 1 and dlq[0][1]["error"] and consumer.dead == 1
    assert r.xpending(S().stream_name, S().consumer_group)["pending"] == 0


def test_transient_failure_is_retried_then_dead_lettered_after_limit(consumer, r, monkeypatch):
    calls = {"n": 0}
    orig = consumer.process_one

    def flaky(msg_id, fields):
        calls["n"] += 1
        raise RuntimeError("database blip")
    monkeypatch.setattr(consumer, "process_one", flaky)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    publish(r, 11)
    consumer.step(block_ms=10)                       # delivery 1 fails -> stays pending
    assert r.xpending(S().stream_name, S().consumer_group)["pending"] == 1 and r.xlen(S().dlq_stream_name) == 0
    consumer._last_reclaim = 0; consumer.step(block_ms=10)   # re-claimed, delivery 2 == max_retries -> DLQ
    assert r.xlen(S().dlq_stream_name) == 1 and r.xpending(S().stream_name, S().consumer_group)["pending"] == 0
    assert "max retries" in r.xrange(S().dlq_stream_name)[0][1]["error"]
    monkeypatch.setattr(consumer, "process_one", orig)


def test_recovers_after_transient_failure(consumer, r, monkeypatch):
    orig, state = consumer.process_one, {"fail": True}

    def once(msg_id, fields):
        if state["fail"]:
            state["fail"] = False
            raise RuntimeError("blip")
        return orig(msg_id, fields)
    monkeypatch.setattr(consumer, "process_one", once); monkeypatch.setattr(time, "sleep", lambda s: None)
    publish(r, 12); consumer.step(block_ms=10)       # fails once inline, succeeds on the in-process retry
    assert db.query_one("SELECT count(*) AS n FROM fraud_predictions WHERE transaction_id = 12")["n"] == 1 and r.xlen(S().dlq_stream_name) == 0


def test_multiple_consumers_share_work_without_overlap(env, r):
    mk = lambda name: Consumer(r, ModelStore("models"), S().model_copy(update={"consumer_name": name}))
    a, b = mk("a"), mk("b"); a.ensure_group()
    for i in range(1, 21):
        publish(r, i)
    for _ in range(6):
        a.step(block_ms=10, count=3); b.step(block_ms=10, count=3)
    assert a.processed + b.processed == 20 and a.processed > 0 and b.processed > 0
    assert db.query_one("SELECT count(*) AS n, count(DISTINCT transaction_id) AS d FROM fraud_predictions") == {"n": 20, "d": 20}


def test_heartbeat_published(consumer, r):
    consumer.step(block_ms=10)
    hb = read_heartbeats(r, "consumer")
    assert hb and hb[0]["name"] == "c-test" and hb[0]["age_s"] < 5


def test_new_source_transactions_are_accepted(consumer, r):
    """A native source can introduce a transaction that is not in the table yet."""
    row = fetch_transaction(5); row["transaction_id"] = 5001
    r.xadd(S().stream_name, encode_event(row))
    consumer.step(block_ms=10)
    assert db.query_one("SELECT count(*) AS n FROM fraud_predictions WHERE transaction_id = 5001")["n"] == 1


def test_producer_emits_replayed_rows_in_order(env, r, monkeypatch):
    import streaming.producer as prod
    monkeypatch.setattr(prod, "get_sync_redis", lambda: r)
    monkeypatch.setattr(prod.time, "sleep", lambda s: None)
    monkeypatch.setenv("PRODUCER_FRAUD_BOOST", "0"); monkeypatch.setenv("PRODUCER_REPLAY_FROM", "all")
    assert prod.run(max_events=5) == 5
    msgs = r.xrange(S().stream_name)
    ids = [json.loads(m[1]["data"])["transaction_id"] for m in msgs]
    assert ids == [1, 2, 3, 4, 5] and "enqueued_at_ms" in msgs[0][1] and r.get(prod.CURSOR_KEY) == "5"
    assert prod.run(max_events=2) == 2 and r.get(prod.CURSOR_KEY) == "7"      # resumes, no replay of 1-5


def test_producer_replays_only_the_held_out_period_by_default(env, r, monkeypatch):
    """Rows up to the model's training boundary must be skipped so live metrics are out-of-sample."""
    import streaming.producer as prod
    monkeypatch.setattr(prod, "get_sync_redis", lambda: r); monkeypatch.setattr(prod.time, "sleep", lambda s: None)
    monkeypatch.setattr(prod, "heldout_cutoff", lambda: 2500.0)            # test rows have time = id * 100  =>  id >= 26
    monkeypatch.setenv("PRODUCER_FRAUD_BOOST", "0"); monkeypatch.setenv("PRODUCER_REPLAY_FROM", "heldout")
    prod.run(max_events=3)
    ids = [json.loads(m[1]["data"])["transaction_id"] for m in r.xrange(S().stream_name)]
    assert ids == [26, 27, 28]
