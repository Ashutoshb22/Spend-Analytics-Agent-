"""Create the DuckDB schema + curated views.

Run once (creates the DuckDB file):
    python scripts/init_db.py
"""
import os
import re

import duckdb
from dotenv import load_dotenv

load_dotenv()

DB = os.environ.get("DUCKDB_PATH", "spend.duckdb")

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "sql", "schema.sql"), "r", encoding="utf-8") as f:
    SCHEMA_SQL = f.read()


def main() -> None:
    # Strip line comments so a ';' inside a comment can't break statement splitting.
    sql = re.sub(r"--[^\n]*", "", SCHEMA_SQL)
    statements = [s.strip() for s in sql.split(";") if s.strip()]
    con = duckdb.connect(DB)
    try:
        for stmt in statements:
            con.execute(stmt)
    finally:
        con.close()
    print(f"init_db: DuckDB schema + views ready at {DB}")


if __name__ == "__main__":
    main()
