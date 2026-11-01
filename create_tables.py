"""REPLACES the old create_tables.py (which hard-coded host/user/password).

Schema is now managed by Alembic migrations. This script is kept so existing commands still
work; it simply runs `alembic upgrade head` using the DB_* / DATABASE_URL environment variables.
"""
import subprocess
import sys

if __name__ == "__main__":
    sys.exit(subprocess.call([sys.executable, "-m", "alembic", "upgrade", "head"]))
