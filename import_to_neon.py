"""REPLACES the old import_to_neon.py (it had a hard-coded Windows path).

Prompts (hidden) for a Neon connection string, strips channel_binding, then runs the shared
idempotent loader. Run migrations against Neon first:  DATABASE_URL=... alembic upgrade head
"""
import argparse
import getpass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from load_data import load


def clean(url: str) -> str:
    p = urlsplit(url)
    q = [(k, v) for k, v in parse_qsl(p.query) if k.lower() != "channel_binding"]
    if not any(k == "sslmode" for k, _ in q):
        q.append(("sslmode", "require"))
    return urlunsplit((p.scheme, p.netloc, p.path, urlencode(q), p.fragment))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="creditcard.csv")
    a = ap.parse_args()
    load(a.csv, clean(getpass.getpass("Paste your Neon connection string (hidden): ")))
