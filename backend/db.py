"""Database access (embedded DuckDB). Reads open the file in read-only mode."""
import threading

import duckdb

from config import settings

# Serialises writers (e.g. file uploads) against each other. DuckDB allows a
# single writer per file, so ingestion takes this lock before opening a
# read-write connection.
DB_LOCK = threading.Lock()


def get_rw_conn() -> "duckdb.DuckDBPyConnection":
    """Read-write connection (used by init_db.py and seed_demo.py)."""
    return duckdb.connect(settings.duckdb_path)


def get_ro_conn() -> "duckdb.DuckDBPyConnection":
    """Read-only connection used by the query executor (defence in depth)."""
    return duckdb.connect(settings.duckdb_path, read_only=True)


def run_select(sql: str, params: list | None = None) -> list[dict]:
    con = get_ro_conn()
    try:
        cur = con.execute(sql, params) if params else con.execute(sql)
        columns = [d[0] for d in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]
    finally:
        con.close()
