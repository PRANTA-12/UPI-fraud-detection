"""WebSocket fan-out: ONE Redis pub/sub subscription, broadcast to every connected browser."""
import asyncio
import json
import logging

import jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from core.config import get_settings
from core.security import decode_token

log = logging.getLogger("api.ws")
router = APIRouter()
MAX_CONNECTIONS = 200


class ConnectionManager:
    def __init__(self):
        self.clients: set[WebSocket] = set()
        self.messages_sent = 0
        self.last_message_at: float | None = None

    async def broadcast(self, text: str) -> None:
        dead = []
        for ws in list(self.clients):
            try:
                await asyncio.wait_for(ws.send_text(text), timeout=2)
                self.messages_sent += 1
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)


manager = ConnectionManager()


async def pubsub_listener(app) -> None:
    """Runs for the life of the app; reconnects on Redis failure."""
    channel = get_settings().alert_channel
    while True:
        try:
            ps = app.state.redis.pubsub()
            await ps.subscribe(channel)
            async for msg in ps.listen():
                if msg.get("type") == "message":
                    manager.last_message_at = asyncio.get_event_loop().time()
                    if manager.clients:
                        await manager.broadcast(msg["data"])
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("pubsub listener error, retrying", extra={"error": str(e)})
            await asyncio.sleep(2)


@router.websocket("/ws/live")
async def live(ws: WebSocket, token: str | None = None):
    s = get_settings()
    if s.ws_require_auth and s.auth_required:
        try:
            decode_token(token or "")
        except jwt.PyJWTError:
            await ws.close(code=4401)          # 4401 = unauthorised
            return
    if len(manager.clients) >= MAX_CONNECTIONS:
        await ws.close(code=4429)
        return
    await ws.accept()
    manager.clients.add(ws)
    await ws.send_text(json.dumps({"type": "hello", "channel": s.alert_channel,
                                   "connections": len(manager.clients)}))
    try:
        while True:
            msg = await ws.receive_text()      # clients may send "ping"
            if msg == "ping":
                await ws.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        pass
    finally:
        manager.clients.discard(ws)
