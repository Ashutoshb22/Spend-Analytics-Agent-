"""Phase 4: Episodic & Long-Term Agent Memory Store.

Stores organizational preferences, custom domain terminology, and historical
question -> SQL execution patterns to improve agent performance over time.
"""

from typing import Any, Dict, List, Optional
import json

from db import DB_LOCK, get_ro_conn, get_rw_conn, run_select


def _ensure_memory_tables() -> None:
    """Lazily initialize agent memory tables in DuckDB."""
    with DB_LOCK:
        con = get_rw_conn()
        try:
            con.execute("""
                CREATE TABLE IF NOT EXISTS agent_user_preference (
                    pref_key     TEXT PRIMARY KEY,
                    pref_value   TEXT NOT NULL,
                    category     TEXT NOT NULL DEFAULT 'general',
                    updated_at   TIMESTAMP NOT NULL DEFAULT current_timestamp
                );
                
                CREATE TABLE IF NOT EXISTS agent_query_pattern (
                    id           BIGINT PRIMARY KEY,
                    question     TEXT NOT NULL,
                    sql_query    TEXT NOT NULL,
                    category     TEXT DEFAULT 'general',
                    use_count    INT NOT NULL DEFAULT 1,
                    created_at   TIMESTAMP NOT NULL DEFAULT current_timestamp
                );
            """)
        finally:
            con.close()


# ---------------------------------------------------------------------------
# Preference Memory API
# ---------------------------------------------------------------------------

def set_preference(key: str, value: str, category: str = "general") -> Dict[str, Any]:
    """Store or update an organizational or user preference."""
    _ensure_memory_tables()
    with DB_LOCK:
        con = get_rw_conn()
        try:
            con.execute(
                "INSERT INTO agent_user_preference(pref_key, pref_value, category, updated_at) "
                "VALUES (?, ?, ?, now()) "
                "ON CONFLICT(pref_key) DO UPDATE SET pref_value = EXCLUDED.pref_value, category = EXCLUDED.category, updated_at = now()",
                [key, str(value), category],
            )
        finally:
            con.close()

    return {"key": key, "value": value, "category": category}


def get_preference(key: str, default: Optional[str] = None) -> Optional[str]:
    """Retrieve a preference value by key."""
    _ensure_memory_tables()
    rows = run_select(f"SELECT pref_value FROM agent_user_preference WHERE pref_key = '{key}'")
    if rows:
        return rows[0]["pref_value"]
    return default


def list_preferences() -> List[Dict[str, Any]]:
    """List all stored preferences."""
    _ensure_memory_tables()
    return run_select("SELECT pref_key, pref_value, category, updated_at FROM agent_user_preference ORDER BY pref_key")


# ---------------------------------------------------------------------------
# Episodic Query Pattern Memory API
# ---------------------------------------------------------------------------

def store_query_pattern(question: str, sql_query: str, category: str = "general") -> Dict[str, Any]:
    """Record a successful question -> SQL pair in long-term memory."""
    _ensure_memory_tables()
    with DB_LOCK:
        con = get_rw_conn()
        try:
            # Check if exact question already exists
            existing = con.execute("SELECT id, use_count FROM agent_query_pattern WHERE question = ?", [question]).fetchone()
            if existing:
                pattern_id = existing[0]
                con.execute("UPDATE agent_query_pattern SET use_count = use_count + 1, sql_query = ? WHERE id = ?", [sql_query, pattern_id])
            else:
                pattern_id = int(con.execute("SELECT COALESCE(MAX(id), 0) FROM agent_query_pattern").fetchone()[0] or 0) + 1
                con.execute(
                    "INSERT INTO agent_query_pattern(id, question, sql_query, category, use_count) "
                    "VALUES (?, ?, ?, ?, 1)",
                    [pattern_id, question, sql_query, category],
                )
        finally:
            con.close()

    return {"id": pattern_id, "question": question, "sql_query": sql_query}


def find_matching_query_patterns(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Retrieve historical query patterns matching user keywords."""
    _ensure_memory_tables()
    sql = "SELECT id, question, sql_query, category, use_count FROM agent_query_pattern ORDER BY use_count DESC LIMIT " + str(limit)
    return run_select(sql)
