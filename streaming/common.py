import json
import logging
import time

log = logging.getLogger("streaming")

HEARTBEAT_TTL_S = 20


def heartbeat(r, role: str, name: str, **fields) -> None:
    key = f"hb:{role}:{name}"
    mapping = {"ts": time.time(), **{k: str(v) for k, v in fields.items()}}
    pipe = r.pipeline()
    pipe.hset(key, mapping=mapping)
    pipe.expire(key, HEARTBEAT_TTL_S)
    pipe.execute()


def read_heartbeats(r, role: str) -> list[dict]:
    out = []
    for key in r.scan_iter(f"hb:{role}:*"):
        h = r.hgetall(key)
        if h:
            h["name"] = key.split(":", 2)[2]
            h["age_s"] = round(time.time() - float(h.get("ts", 0)), 1)
            out.append(h)
    return sorted(out, key=lambda d: d["name"])


def encode_event(payload: dict) -> dict:
    """Wire format of a stream message. A native UPI source only has to produce this same shape."""
    return {"data": json.dumps(payload, default=str), "enqueued_at_ms": str(int(time.time() * 1000))}
