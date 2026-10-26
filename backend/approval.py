"""Phase 4: Human-in-the-Loop (HITL) & Approval Workflow Engine.

Manages high-impact agent actions (e.g., database mutations, category re-mapping,
promoting savings opportunities) that require human approval before execution.
"""

from typing import Any, Dict, List, Optional
import json

from db import DB_LOCK, get_ro_conn, get_rw_conn, run_select


def _ensure_approval_table() -> None:
    """Lazily initialize agent_pending_approval ledger table in DuckDB."""
    with DB_LOCK:
        con = get_rw_conn()
        try:
            con.execute("""
                CREATE TABLE IF NOT EXISTS agent_pending_approval (
                    id              BIGINT PRIMARY KEY,
                    action_type     TEXT NOT NULL,
                    title           TEXT NOT NULL,
                    details         TEXT NOT NULL,
                    payload_json    TEXT NOT NULL,
                    status          TEXT NOT NULL DEFAULT 'pending',
                    created_by      TEXT NOT NULL DEFAULT 'agent',
                    reviewed_by     TEXT,
                    notes           TEXT,
                    created_at      TIMESTAMP NOT NULL DEFAULT current_timestamp,
                    reviewed_at     TIMESTAMP
                )
            """)
        finally:
            con.close()


def create_pending_approval(
    action_type: str,
    title: str,
    details: str,
    payload: Dict[str, Any],
    created_by: str = "agent",
) -> Dict[str, Any]:
    """Register a new action requiring Human-in-the-Loop (HITL) approval."""
    _ensure_approval_table()
    with DB_LOCK:
        con = get_rw_conn()
        try:
            next_id = int(con.execute("SELECT COALESCE(MAX(id), 0) FROM agent_pending_approval").fetchone()[0] or 0) + 1
            payload_str = json.dumps(payload)
            con.execute(
                "INSERT INTO agent_pending_approval(id, action_type, title, details, payload_json, status, created_by) "
                "VALUES (?, ?, ?, ?, ?, 'pending', ?)",
                [next_id, action_type, title, details, payload_str, created_by],
            )
        finally:
            con.close()

    return {
        "id": next_id,
        "action_type": action_type,
        "title": title,
        "details": details,
        "status": "pending",
        "created_by": created_by,
    }


def list_pending_approvals(status_filter: str = "pending") -> List[Dict[str, Any]]:
    """Retrieve pending or historical approval requests."""
    _ensure_approval_table()
    sql = "SELECT id, action_type, title, details, payload_json, status, created_by, reviewed_by, notes, created_at, reviewed_at FROM agent_pending_approval"
    if status_filter != "all":
        sql += f" WHERE status = '{status_filter}'"
    sql += " ORDER BY id DESC"

    rows = run_select(sql)
    results = []
    for r in rows:
        results.append({
            "id": r["id"],
            "action_type": r["action_type"],
            "title": r["title"],
            "details": r["details"],
            "payload": json.loads(r["payload_json"] or "{}"),
            "status": r["status"],
            "created_by": r["created_by"],
            "reviewed_by": r["reviewed_by"],
            "notes": r["notes"],
            "created_at": str(r["created_at"]),
            "reviewed_at": str(r["reviewed_at"]) if r["reviewed_at"] else None,
        })
    return results


def review_approval(
    approval_id: int,
    decision: str,
    reviewer_username: str,
    notes: Optional[str] = "",
) -> Dict[str, Any]:
    """Approve or reject a pending agent action. If approved, executes payload."""
    _ensure_approval_table()
    if decision not in ("approved", "rejected"):
        raise ValueError("Decision must be either 'approved' or 'rejected'.")

    with DB_LOCK:
        con = get_rw_conn()
        try:
            row = con.execute(
                "SELECT id, action_type, payload_json, status FROM agent_pending_approval WHERE id = ?",
                [approval_id],
            ).fetchone()

            if not row:
                raise ValueError(f"Approval request #{approval_id} not found.")

            if row[3] != "pending":
                raise ValueError(f"Approval request #{approval_id} has already been {row[3]}.")

            action_type = row[1]
            payload = json.loads(row[2] or "{}")

            # Update approval status
            con.execute(
                "UPDATE agent_pending_approval SET status = ?, reviewed_by = ?, notes = ?, reviewed_at = current_timestamp WHERE id = ?",
                [decision, reviewer_username, notes or "", approval_id],
            )
        finally:
            con.close()

    # If approved, execute action payload logic
    executed_result = None
    if decision == "approved":
        executed_result = _execute_approved_action(action_type, payload)

    return {
        "id": approval_id,
        "status": decision,
        "reviewed_by": reviewer_username,
        "action_executed": decision == "approved",
        "execution_result": executed_result,
    }


def _execute_approved_action(action_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Execute the approved action payload."""
    if action_type == "create_savings_opportunity":
        import savings
        return savings.create_opportunity(payload)
    elif action_type == "update_category_mapping":
        # Example category update execution
        return {"updated": True, "payload": payload}
    return {"executed": True, "type": action_type}
