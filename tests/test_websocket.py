import json

import pytest
from starlette.websockets import WebSocketDisconnect

from core.config import get_settings


def test_ws_rejects_missing_or_bad_token(client):
    for url in ("/ws/live", "/ws/live?token=garbage"):
        with pytest.raises(WebSocketDisconnect) as e:
            with client.websocket_connect(url):
                pass
        assert e.value.code == 4401


def test_ws_accepts_valid_token_and_pings(client, admin):
    token = admin["Authorization"].split()[1]
    with client.websocket_connect(f"/ws/live?token={token}") as ws:
        assert ws.receive_json()["type"] == "hello"
        ws.send_text("ping"); assert ws.receive_json() == {"type": "pong"}


def test_ws_broadcasts_published_predictions(client, admin, fake_server):
    import fakeredis
    token = admin["Authorization"].split()[1]
    pub = fakeredis.FakeStrictRedis(server=fake_server, decode_responses=True)
    with client.websocket_connect(f"/ws/live?token={token}") as ws:
        ws.receive_json()
        import time
        got = None
        for _ in range(40):                                  # wait for the background subscriber to attach
            pub.publish(get_settings().alert_channel, json.dumps({"type": "prediction", "transaction_id": 42, "alert": True}))
            time.sleep(0.05)
            try:
                got = ws.receive_json(); break
            except Exception:
                continue
        assert got and got["transaction_id"] == 42
