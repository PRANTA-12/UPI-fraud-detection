"""REPLACES the old test_db.py, which contained a hard-coded database password.
(If that password was ever committed to GitHub, rotate it and purge it from git history.)

Quick connectivity/sanity check:  python test_db.py     (uses DB_* env vars / .env)
"""
from core import db

if __name__ == "__main__":
    print("Database connected:", db.ping())
    print("Tables:", [r["table_name"] for r in db.query_all(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY 1")])
    print("Total transactions:", db.query_one("SELECT COUNT(*) AS n FROM transactions")["n"])
    print("Distribution:", db.query_all(
        "SELECT actual_class, COUNT(*) AS n FROM transactions GROUP BY 1 ORDER BY 1"))
