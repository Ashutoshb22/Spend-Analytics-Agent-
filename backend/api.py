"""FastAPI surface for the Spend Analytics Agent (minimal slice).
Run from the backend/ directory:
  python -m uvicorn api:app --host 127.0.0.1 --port 8000
"""
from dotenv import load_dotenv

load_dotenv()

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile  # noqa: E402
from pydantic import BaseModel  # noqa: E402

import hashlib  # noqa: E402
import os  # noqa: E402
import threading  # noqa: E402
import uuid  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

from fastapi.staticfiles import StaticFiles  # noqa: E402

from config import settings  # noqa: E402
import documents  # noqa: E402
import savings  # noqa: E402
from classify import classify_upload  # noqa: E402
from db import DB_LOCK, get_ro_conn, get_rw_conn, run_select  # noqa: E402
from graph import answer_question  # noqa: E402
from ingest import ingest_bytes  # noqa: E402
from metrics import compute_metrics  # noqa: E402


def _warm_slm() -> None:
    """Pre-load the SLM in the background so the first real query isn't cold."""
    try:
        from llm import chat

        chat([{"role": "user", "content": "ok"}], max_tokens=1)
    except Exception:  # noqa: BLE001 - warm-up is best-effort
        pass


ROLES = {"admin", "worker"}
SESSION_TTL_SECONDS = 60 * 60 * 8
SESSIONS_LOCK = threading.Lock()


def _norm_role(role: str | None) -> str:
    value = (role or "").strip().lower()
    if value in ("viewer", "manager"):
        return "worker"
    return value


def _hash_password(password: str, salt: str) -> str:
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000)
    return digest.hex()


def _verify_password(password: str, salt: str, expected_hash: str) -> bool:
    return _hash_password(password, salt) == expected_hash


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _audit(action: str, username: str, detail: str = "") -> None:
    with DB_LOCK:
        con = get_rw_conn()
        try:
            next_id = int(con.execute("SELECT COALESCE(MAX(id), 0) FROM auth_audit_log").fetchone()[0] or 0) + 1
            con.execute(
                "INSERT INTO auth_audit_log(id, ts, username, action, detail) VALUES (?, ?, ?, ?, ?)",
                [next_id, _now_iso(), username, action, detail],
            )
        finally:
            con.close()


def _record_upload(username: str, filename: str, mode: str, rows_added: int,
                   is_spend: bool, category: str) -> None:
    """Append one row to the upload history ledger (who uploaded what, when)."""
    with DB_LOCK:
        con = get_rw_conn()
        try:
            next_id = int(con.execute("SELECT COALESCE(MAX(id), 0) FROM upload_history").fetchone()[0] or 0) + 1
            con.execute(
                "INSERT INTO upload_history(id, ts, username, filename, mode, rows_added, is_spend, category) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [next_id, _now_iso(), username, filename, mode, int(rows_added), bool(is_spend), category],
            )
        finally:
            con.close()


def _ensure_auth_tables() -> None:
    default_admin_user = os.environ.get("APP_ADMIN_USER", "admin").strip() or "admin"
    default_admin_pass = os.environ.get("APP_ADMIN_PASS", "admin123")
    default_worker_user = os.environ.get("APP_WORKER_USER", "worker").strip() or "worker"
    default_worker_pass = os.environ.get("APP_WORKER_PASS", "worker123")

    with DB_LOCK:
        con = get_rw_conn()
        try:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_user (
                    username TEXT PRIMARY KEY,
                    password_salt TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT current_timestamp,
                    updated_at TIMESTAMP DEFAULT current_timestamp
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_audit_log (
                    id BIGINT PRIMARY KEY,
                    ts TEXT NOT NULL,
                    username TEXT NOT NULL,
                    action TEXT NOT NULL,
                    detail TEXT
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_session (
                    token TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    role TEXT NOT NULL,
                    expires_at BIGINT NOT NULL,
                    created_at TIMESTAMP DEFAULT current_timestamp
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS upload_history (
                    id BIGINT PRIMARY KEY,
                    ts TEXT NOT NULL,
                    username TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    rows_added BIGINT NOT NULL DEFAULT 0,
                    is_spend BOOLEAN NOT NULL DEFAULT FALSE,
                    category TEXT
                )
                """
            )
            # Backward compatibility: collapse legacy manager role into worker.
            con.execute("UPDATE auth_user SET role = 'worker' WHERE lower(role) = 'manager'")
            users_count = int(con.execute("SELECT COUNT(*) FROM auth_user").fetchone()[0])
            if users_count == 0:
                defaults = [
                    (default_admin_user, default_admin_pass, "admin"),
                    (default_worker_user, default_worker_pass, "worker"),
                ]
                for username, password, role in defaults:
                    salt = uuid.uuid4().hex
                    con.execute(
                        "INSERT INTO auth_user(username, password_salt, password_hash, role, is_active) VALUES (?, ?, ?, ?, TRUE)",
                        [username, salt, _hash_password(password, salt), role],
                    )
        finally:
            con.close()


def _read_user(username: str) -> dict | None:
    _ensure_auth_tables()
    with DB_LOCK:
        con = get_rw_conn()
        try:
            row = con.execute(
                "SELECT username, password_salt, password_hash, role, is_active FROM auth_user WHERE username = ?",
                [username],
            ).fetchone()
        finally:
            con.close()
    if not row:
        return None
    return {
        "username": row[0],
        "password_salt": row[1],
        "password_hash": row[2],
        "role": _norm_role(row[3]),
        "is_active": bool(row[4]),
    }


def _create_session(username: str, role: str) -> str:
    token = uuid.uuid4().hex
    now = int(datetime.now(timezone.utc).timestamp())
    with DB_LOCK:
        con = get_rw_conn()
        try:
            con.execute(
                "INSERT INTO auth_session(token, username, role, expires_at) VALUES (?, ?, ?, ?)",
                [token, username, _norm_role(role), now + SESSION_TTL_SECONDS],
            )
        finally:
            con.close()
    return token


def _require_user(authorization: str = Header(default="")) -> dict:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token.")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token.")
    now = int(datetime.now(timezone.utc).timestamp())
    con = get_ro_conn()
    try:
        row = con.execute(
            "SELECT username, role, expires_at FROM auth_session WHERE token = ?",
            [token],
        ).fetchone()
    finally:
        con.close()
    if not row:
        raise HTTPException(status_code=401, detail="Invalid session.")
    if int(row[2]) < now:
        with DB_LOCK:
            con = get_rw_conn()
            try:
                con.execute("DELETE FROM auth_session WHERE token = ?", [token])
            finally:
                con.close()
        raise HTTPException(status_code=401, detail="Session expired. Please sign in again.")
    return {"username": row[0], "role": _norm_role(row[1]), "expires_at": int(row[2])}


def require_roles(*allowed: str):
    allowed_set = {_norm_role(role) for role in allowed}

    def _dep(user: dict = Depends(_require_user)):
        if _norm_role(user.get("role")) not in allowed_set:
            raise HTTPException(status_code=403, detail="You do not have permission for this action.")
        return user

    return _dep


@asynccontextmanager
async def lifespan(app: FastAPI):
    _ensure_auth_tables()
    if settings.warm_slm_on_start and settings.slm_base_url and settings.slm_api_key:
        threading.Thread(target=_warm_slm, daemon=True).start()
    yield


app = FastAPI(title="Spend Analytics Agent", version="0.1.0", lifespan=lifespan)

MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB cap on uploaded files
ALLOWED_UPLOAD_EXT = (
    ".csv", ".tsv", ".txt", ".xlsx", ".xlsm", ".xls",
    ".png", ".jpg", ".jpeg", ".webp", ".pdf",
)
ALLOWED_DOC_EXT = (".pdf", ".docx", ".docm", ".txt")


class AskRequest(BaseModel):
    q: str


class SavingsCreate(BaseModel):
    title: str
    kind: str | None = "custom"
    category: str | None = None
    supplier: str | None = None
    item: str | None = None
    target_annual: float | None = None
    status: str | None = "identified"
    owner: str | None = None
    rationale: str | None = None
    source: str | None = "manual"


class SavingsUpdate(BaseModel):
    status: str | None = None
    title: str | None = None
    target_annual: float | None = None
    owner: str | None = None
    rationale: str | None = None
    baseline_date: str | None = None


class LoginRequest(BaseModel):
    username: str
    password: str


class UserCreate(BaseModel):
    username: str
    password: str
    role: str


class UserRoleUpdate(BaseModel):
    role: str


@app.get("/health")
def health():
    con = None
    try:
        con = get_ro_conn()
        con.execute("SELECT 1")
        con.fetchone()
        return {"status": "ok", "db": "up"}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"DB not reachable: {e}")
    finally:
        if con is not None:
            con.close()


@app.post("/auth/login")
def auth_login(req: LoginRequest):
    username = req.username.strip()
    password = req.password
    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password are required.")
    user = _read_user(username)
    if not user or not user["is_active"]:
        raise HTTPException(status_code=401, detail="Invalid Username")
    if not _verify_password(password, user["password_salt"], user["password_hash"]):
        raise HTTPException(status_code=401, detail="Incorrect Password")
    token = _create_session(user["username"], user["role"])
    _audit("login", user["username"], f"role={user['role']}")
    return {
        "token": token,
        "user": {"username": user["username"], "role": user["role"]},
        "expires_in": SESSION_TTL_SECONDS,
    }


@app.post("/auth/logout")
def auth_logout(user: dict = Depends(_require_user), authorization: str = Header(default="")):
    token = authorization.removeprefix("Bearer ").strip() if authorization.startswith("Bearer ") else ""
    with DB_LOCK:
        con = get_rw_conn()
        try:
            con.execute("DELETE FROM auth_session WHERE token = ?", [token])
        finally:
            con.close()
    _audit("logout", user["username"], "")
    return {"ok": True}


@app.get("/auth/me")
def auth_me(user: dict = Depends(_require_user)):
    return {"username": user["username"], "role": _norm_role(user["role"])}


@app.get("/auth/users")
def auth_users(current: dict = Depends(require_roles("admin"))):
    con = get_ro_conn()
    try:
        rows = con.execute(
            "SELECT username, role, is_active, created_at, updated_at FROM auth_user ORDER BY username"
        ).fetchall()
    finally:
        con.close()
    users = [
        {
            "username": row[0],
            "role": _norm_role(row[1]),
            "is_active": bool(row[2]),
            "created_at": str(row[3]),
            "updated_at": str(row[4]),
        }
        for row in rows
    ]
    return {"users": users}


@app.post("/auth/users")
def auth_create_user(req: UserCreate, current: dict = Depends(require_roles("admin"))):
    username = req.username.strip()
    password = req.password
    role = _norm_role(req.role)
    if not username:
        raise HTTPException(status_code=400, detail="Username is required.")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")
    if role not in ROLES:
        raise HTTPException(status_code=400, detail="role must be admin or worker.")
    with DB_LOCK:
        con = get_rw_conn()
        try:
            exists = con.execute("SELECT 1 FROM auth_user WHERE username = ?", [username]).fetchone()
            if exists:
                raise HTTPException(status_code=409, detail="User already exists.")
            salt = uuid.uuid4().hex
            con.execute(
                "INSERT INTO auth_user(username, password_salt, password_hash, role, is_active) VALUES (?, ?, ?, ?, TRUE)",
                [username, salt, _hash_password(password, salt), role],
            )
            con.execute("UPDATE auth_user SET updated_at = current_timestamp WHERE username = ?", [username])
        finally:
            con.close()
    _audit("create-user", current["username"], f"username={username};role={role}")
    return {"username": username, "role": role, "is_active": True}


@app.patch("/auth/users/{username}/role")
def auth_update_user_role(username: str, req: UserRoleUpdate, current: dict = Depends(require_roles("admin"))):
    role = _norm_role(req.role)
    if role not in ROLES:
        raise HTTPException(status_code=400, detail="role must be admin or worker.")
    with DB_LOCK:
        con = get_rw_conn()
        try:
            row = con.execute("SELECT role FROM auth_user WHERE username = ?", [username]).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="No such user.")
            con.execute(
                "UPDATE auth_user SET role = ?, updated_at = current_timestamp WHERE username = ?",
                [role, username],
            )
        finally:
            con.close()
    _audit("update-user-role", current["username"], f"username={username};role={role}")
    return {"username": username, "role": role}


@app.delete("/auth/users/{username}")
def auth_delete_user(username: str, current: dict = Depends(require_roles("admin"))):
    if username == current["username"]:
        raise HTTPException(status_code=400, detail="You cannot delete your own active account.")
    with DB_LOCK:
        con = get_rw_conn()
        try:
            row = con.execute("SELECT role FROM auth_user WHERE username = ?", [username]).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="No such user.")
            if _norm_role(row[0]) == "admin":
                admin_count = int(
                    con.execute("SELECT COUNT(*) FROM auth_user WHERE lower(role) = 'admin'").fetchone()[0]
                )
                if admin_count <= 1:
                    raise HTTPException(status_code=400, detail="Cannot delete the last admin account.")
            con.execute("DELETE FROM auth_user WHERE username = ?", [username])
        finally:
            con.close()
    _audit("delete-user", current["username"], f"username={username}")
    return {"deleted": username}


@app.post("/ask")
def ask(req: AskRequest, user: dict = Depends(require_roles("admin", "worker"))):
    if not req.q.strip():
        raise HTTPException(status_code=400, detail="Empty question.")
    try:
        result = answer_question(req.q)
        _audit("ask", user["username"], req.q.strip()[:200])
        return result
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e))


def _cleaned_sample(limit: int = 25) -> list[dict]:
    """A small preview of the cleaned/loaded rows for the dashboard."""
    try:
        return run_select(
            "SELECT invoice_date, supplier_name, category_level2 AS category, bu_name, "
            "qty, unit_price, amount, is_maverick, contract_id "
            f"FROM vw_spend ORDER BY amount DESC NULLS LAST LIMIT {int(limit)}"
        )
    except Exception:  # noqa: BLE001 - preview is best-effort
        return []


@app.get("/metrics")
def metrics(
    start_date: str | None = None,
    end_date: str | None = None,
    user: dict = Depends(require_roles("admin", "worker")),
):
    """Deterministic dashboard metrics over the current working dataset,
    optionally scoped to an inclusive invoice-date range (YYYY-MM-DD)."""
    try:
        return compute_metrics(start_date=start_date, end_date=end_date)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Could not compute metrics: {e}")


@app.get("/breakdown")
def breakdown(dim: str, value: str, user: dict = Depends(require_roles("admin", "worker"))):
    """Drill-down for a dashboard bar: which items make up a supplier's or a
    category's spend. `dim` is 'supplier' or 'category'; `value` is bound as a
    query parameter (no string interpolation) so it stays injection-safe."""
    col = {"supplier": "supplier_name", "category": "category_level2", "bu": "bu_name"}.get(dim.lower())
    if not col:
        raise HTTPException(status_code=400, detail="dim must be 'supplier', 'category' or 'bu'.")
    try:
        items = run_select(
            "SELECT COALESCE(item, '(unspecified)') AS item, COUNT(*) AS lines, "
            "COALESCE(SUM(qty), 0) AS qty, SUM(amount) AS spend "
            f"FROM vw_spend WHERE {col} = ? GROUP BY 1 ORDER BY spend DESC LIMIT 50",
            [value],
        )
        summary = run_select(
            f"SELECT COALESCE(SUM(amount), 0) AS total, COUNT(*) AS lines FROM vw_spend WHERE {col} = ?",
            [value],
        )[0]
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Could not load breakdown: {e}")
    return {
        "dim": dim.lower(),
        "value": value,
        "items": items,
        "total": summary["total"],
        "lines": summary["lines"],
    }


@app.get("/lines")
def lines(dim: str, value: str, item: str, user: dict = Depends(require_roles("admin", "worker"))):
    """Second-level drill-down: the individual spend lines (invoice records) behind one
    item within a supplier / category / business unit. Values are bound parameters."""
    col = {"supplier": "supplier_name", "category": "category_level2", "bu": "bu_name"}.get(dim.lower())
    if not col:
        raise HTTPException(status_code=400, detail="dim must be 'supplier', 'category' or 'bu'.")
    try:
        rows = run_select(
            "SELECT invoice_date, qty, unit_price, amount "
            f"FROM vw_spend WHERE {col} = ? AND COALESCE(item, '(unspecified)') = ? "
            "ORDER BY invoice_date NULLS LAST, amount DESC LIMIT 200",
            [value, item],
        )
        summary = run_select(
            f"SELECT COALESCE(SUM(amount), 0) AS total, COUNT(*) AS lines "
            f"FROM vw_spend WHERE {col} = ? AND COALESCE(item, '(unspecified)') = ?",
            [value, item],
        )[0]
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Could not load lines: {e}")
    return {
        "dim": dim.lower(),
        "value": value,
        "item": item,
        "rows": rows,
        "total": summary["total"],
        "lines": summary["lines"],
    }


@app.post("/upload")
async def upload(
    file: UploadFile = File(...),
    mode: str = Form("replace"),
    user: dict = Depends(require_roles("admin")),
):
    """Upload a spend file. An AI agent first classifies what kind of data it is,
    then (only if it is analysable spend data) it is cleaned, loaded and analysed.
    Returns the classification, plus the cleaning summary, metrics and a preview."""
    name = file.filename or "upload"
    if not name.lower().endswith(ALLOWED_UPLOAD_EXT):
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Upload a CSV, TSV, Excel, image or PDF file.",
        )
    if mode not in ("replace", "append"):
        raise HTTPException(status_code=400, detail="mode must be 'replace' or 'append'.")
    if mode == "replace" and _norm_role(user.get("role")) != "admin":
        raise HTTPException(status_code=403, detail="Only admins can replace the full dataset.")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 25 MB).")

    classification = classify_upload(content, name)
    result = {
        "classification": classification,
        "summary": None,
        "metrics": None,
        "sample": None,
        "message": None,
    }

    if classification.get("is_spend"):
        try:
            result["summary"] = ingest_bytes(content, name, mode=mode)
            result["metrics"] = compute_metrics()
            result["sample"] = _cleaned_sample()
        except ValueError as e:
            result["message"] = (
                f"Detected as \u201c{classification['category']}\u201d, but it couldn't be "
                f"loaded as spend: {e}"
            )
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"Could not process file: {e}")
    else:
        result["message"] = (
            f"This looks like \u201c{classification['category']}\u201d, which isn't procurement "
            "spend data, so the spend dashboard was left unchanged."
        )
    summary = result.get("summary") or {}
    rows_added = int(summary.get("rows_loaded") or 0)
    _record_upload(
        user["username"], name, mode, rows_added,
        bool(classification.get("is_spend")), classification.get("category") or "",
    )
    _audit("upload", user["username"], f"filename={name};mode={mode};is_spend={bool(classification.get('is_spend'))}")
    return result


@app.get("/upload-history")
def upload_history(user: dict = Depends(require_roles("admin"))):
    """Recent spend-file uploads: filename, when, who uploaded it, and rows added.

    Read-only: the ``upload_history`` table is created at startup, so we never open
    a read-write connection here (doing so clashes with the concurrent read-only
    connections other endpoints hold). If the table is somehow absent, we simply
    report an empty history rather than erroring.
    """
    con = get_ro_conn()
    try:
        rows = con.execute(
            "SELECT ts, username, filename, mode, rows_added, is_spend, category "
            "FROM upload_history ORDER BY id DESC LIMIT 50"
        ).fetchall()
    except Exception:  # noqa: BLE001 - table not created yet -> nothing to show
        rows = []
    finally:
        con.close()
    history = [
        {
            "ts": r[0],
            "username": r[1],
            "filename": r[2],
            "mode": r[3],
            "rows_added": int(r[4] or 0),
            "is_spend": bool(r[5]),
            "category": r[6],
        }
        for r in rows
    ]
    return {"history": history}


@app.get("/documents")
def documents_list(user: dict = Depends(require_roles("admin", "worker"))):
    """List the contract / policy documents that have been indexed."""
    return {"documents": documents.list_documents()}


@app.delete("/documents")
def documents_delete(name: str, user: dict = Depends(require_roles("admin"))):
    """Remove an indexed contract / policy document by name."""
    removed = documents.remove_document(name)
    if not removed:
        raise HTTPException(status_code=404, detail=f"No indexed document named '{name}'.")
    _audit("delete-document", user["username"], name)
    return {"removed": removed, "documents": documents.list_documents()}


@app.post("/upload-doc")
async def upload_doc(file: UploadFile = File(...), user: dict = Depends(require_roles("admin"))):
    """Upload a contract or policy document (PDF / Word / text). Its text is extracted
    and indexed so the agent can cite it alongside the spend numbers."""
    name = file.filename or "document"
    if not name.lower().endswith(ALLOWED_DOC_EXT):
        raise HTTPException(
            status_code=400,
            detail="Unsupported document type. Upload a PDF, Word (.docx) or text file.",
        )
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="The document is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Document too large (max 25 MB).")
    try:
        summary = documents.add_document(name, content)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Could not read document: {e}")
    _audit("upload-document", user["username"], name)
    return {"summary": summary, "documents": documents.list_documents()}


# --- Savings realisation tracker -------------------------------------------------
@app.get("/savings")
def savings_list(user: dict = Depends(require_roles("admin", "worker"))):
    """Every tracked savings opportunity plus the pipeline rollup."""
    try:
        return savings.list_opportunities()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Could not load savings: {e}")


@app.get("/savings/opportunities")
def savings_opportunities(user: dict = Depends(require_roles("admin", "worker"))):
    """Agent-detected savings opportunities that aren't being tracked yet."""
    try:
        return {"suggestions": savings.detect_opportunities()}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Could not detect opportunities: {e}")


@app.post("/savings")
def savings_create(req: SavingsCreate, user: dict = Depends(require_roles("admin"))):
    """Track a new savings opportunity (manually, or by promoting a suggestion)."""
    try:
        out = savings.create_opportunity(req.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Could not create opportunity: {e}")
    _audit("create-savings", user["username"], out.get("title", ""))
    return out


@app.patch("/savings/{opp_id}")
def savings_update(opp_id: int, req: SavingsUpdate, user: dict = Depends(require_roles("admin"))):
    """Advance an opportunity's status or edit its fields."""
    try:
        updated = savings.update_opportunity(opp_id, req.model_dump(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Could not update opportunity: {e}")
    if updated is None:
        raise HTTPException(status_code=404, detail="No such savings opportunity.")
    _audit("update-savings", user["username"], f"id={opp_id};status={updated.get('status')}")
    return updated


@app.delete("/savings/{opp_id}")
def savings_delete(opp_id: int, user: dict = Depends(require_roles("admin"))):
    """Remove a tracked savings opportunity."""
    try:
        removed = savings.delete_opportunity(opp_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Could not delete opportunity: {e}")
    if not removed:
        raise HTTPException(status_code=404, detail="No such savings opportunity.")
    _audit("delete-savings", user["username"], f"id={opp_id}")
    return {"deleted": opp_id}


# --- Phase 3: Multi-Agent & Proactive Audit Endpoints -----------------------------

class MultiAgentQueryRequest(BaseModel):
    question: str
    vendor: Optional[str] = None


@app.post("/api/agent/multi-agent")
def multi_agent_query(req: MultiAgentQueryRequest, user: dict = Depends(require_roles("admin", "worker"))):
    """Invoke Phase 3 Supervisor Agent to orchestrate specialized sub-agents."""
    try:
        from agents import SupervisorAgent
        supervisor = SupervisorAgent()
        return supervisor.process_multi_agent_request(req.question, vendor=req.vendor)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Multi-agent orchestration failed: {e}")


@app.post("/api/agent/proactive-audit")
def proactive_spend_audit(user: dict = Depends(require_roles("admin", "worker"))):
    """Run Phase 3 Autonomous Background Spend Audit Engine."""
    try:
        from agents import run_proactive_spend_audit
        return run_proactive_spend_audit()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Proactive spend audit failed: {e}")


# --- Phase 4: Human-in-the-Loop (HITL) & Memory Endpoints ------------------------

class ApprovalReviewRequest(BaseModel):
    decision: str
    notes: Optional[str] = ""


class PreferenceSetRequest(BaseModel):
    key: str
    value: str
    category: Optional[str] = "general"


@app.get("/api/agent/approvals")
def get_approvals(status: str = "pending", user: dict = Depends(require_roles("admin", "worker"))):
    """Retrieve pending or past HITL agent approvals."""
    try:
        import approval
        return {"approvals": approval.list_pending_approvals(status_filter=status)}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Could not list approvals: {e}")


@app.post("/api/agent/approvals/{approval_id}/review")
def review_approval_endpoint(approval_id: int, req: ApprovalReviewRequest, user: dict = Depends(require_roles("admin"))):
    """Approve or reject a pending agent action."""
    try:
        import approval
        return approval.review_approval(approval_id, req.decision, reviewer_username=user["username"], notes=req.notes)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Approval review failed: {e}")


@app.get("/api/agent/memory/preferences")
def get_preferences_endpoint(user: dict = Depends(require_roles("admin", "worker"))):
    """List stored organizational preferences."""
    try:
        import memory
        return {"preferences": memory.list_preferences()}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Could not list preferences: {e}")


@app.post("/api/agent/memory/preferences")
def set_preference_endpoint(req: PreferenceSetRequest, user: dict = Depends(require_roles("admin"))):
    """Set or update an organizational preference."""
    try:
        import memory
        return memory.set_preference(req.key, req.value, category=req.category)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Could not save preference: {e}")


# --- Static frontend (built React app) -------------------------------------------
# Mounted LAST so every API route above takes precedence; this then serves the SPA
# at "/" and its hashed assets. For development, run `npm run dev` in frontend/.
_STATIC_DIR = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend", "dist")
)
if os.path.isdir(_STATIC_DIR):
    app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="app")
