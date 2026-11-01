"""REPLACES the old load_data.py.

Fixes over the original:
  * idempotent: refuses to double-load (count==expected -> no-op; partial -> clear error)
  * transaction_id = CSV row number (1..N), matching import_to_neon.py, and the SERIAL sequence is
    advanced afterwards so future inserts cannot collide
  * fast COPY instead of row batches; credentials only from environment / --database-url

Usage:
    python load_data.py                       # uses DB_* env vars, CSV at /app/creditcard.csv
    python load_data.py --csv creditcard.csv --database-url "postgresql://..."
"""
import argparse
import io
import os
import sys

import pandas as pd
import psycopg2

EXPECTED_ROWS = 284_807
COLUMNS = ["transaction_time", "amount", *[f"v{i}" for i in range(1, 29)], "actual_class"]
RENAME = {"Time": "transaction_time", "Amount": "amount", "Class": "actual_class",
          **{f"V{i}": f"v{i}" for i in range(1, 29)}}


def dsn_from_env() -> str:
    from core.config import get_settings
    return get_settings().dsn


def load(csv_path: str, dsn: str, chunk: int = 20_000) -> int:
    conn = psycopg2.connect(dsn, connect_timeout=20)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM transactions")
            existing = cur.fetchone()[0]
        if existing == EXPECTED_ROWS:
            print(f"transactions already contains {existing:,} rows - nothing to do.", flush=True)
            return existing
        if existing != 0:
            raise SystemExit(f"transactions has {existing:,} rows (expected 0 or {EXPECTED_ROWS:,}). "
                             "Refusing to load to avoid duplicates. Truncate the table first if intended.")
        total = 0
        cols = ["transaction_id", *COLUMNS]
        with conn.cursor() as cur:
            for df in pd.read_csv(csv_path, chunksize=chunk):
                df = df.rename(columns=RENAME)[COLUMNS]
                df.insert(0, "transaction_id", range(total + 1, total + len(df) + 1))
                buf = io.StringIO()
                df.to_csv(buf, index=False, header=False)
                buf.seek(0)
                cur.copy_expert(f"COPY transactions ({', '.join(cols)}) FROM STDIN WITH CSV", buf)
                total += len(df)
                print(f"Loaded {total:,}/{EXPECTED_ROWS:,}", flush=True)
            cur.execute("SELECT setval(pg_get_serial_sequence('transactions','transaction_id'), "
                        "(SELECT MAX(transaction_id) FROM transactions))")
        conn.commit()
        if total != EXPECTED_ROWS:
            print(f"WARNING: loaded {total:,} rows; the standard dataset has {EXPECTED_ROWS:,}.", file=sys.stderr)
        print("Data loading completed successfully!", flush=True)
        return total
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=os.getenv("CSV_PATH", "/app/creditcard.csv"))
    ap.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    a = ap.parse_args()
    load(a.csv, a.database_url or dsn_from_env())
