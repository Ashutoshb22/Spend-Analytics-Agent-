import React, { useEffect, useRef, useState } from "react";
import {
  apiUpload,
  apiDocuments,
  apiUploadDoc,
  apiRemoveDoc,
  apiUsers,
  apiCreateUser,
  apiUpdateUserRole,
  apiDeleteUser,
  apiUploadHistory,
} from "../api.js";
import { num, moneyFull } from "../format.js";

export default function Upload({ user, onAnalysed, onViewDashboard }) {
  const role = (user && user.role) || "worker";
  const canAppend = role === "admin";
  const canReplace = role === "admin";
  const canManageUsers = role === "admin";

  const [mode, setMode] = useState("append");
  const [upStatus, setUpStatus] = useState("");
  const [uploadError, setUploadError] = useState("");
  const [result, setResult] = useState(null); // the /upload response
  const [dragSpend, setDragSpend] = useState(false);
  const [dragDoc, setDragDoc] = useState(false);
  const [docs, setDocs] = useState([]);
  const [docStatus, setDocStatus] = useState("");
  const [docError, setDocError] = useState("");
  const [uploads, setUploads] = useState([]);
  const [users, setUsers] = useState([]);
  const [userStatus, setUserStatus] = useState("");
  const [userError, setUserError] = useState("");
  const [newUsername, setNewUsername] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newRole, setNewRole] = useState("worker");
  const fileRef = useRef(null);
  const docFileRef = useRef(null);

  useEffect(() => {
    loadDocs();
    if (canManageUsers) loadUsers();
    if (canManageUsers) loadUploads();
    if (!canReplace && mode === "replace") setMode("append");
  }, []);

  async function loadDocs() {
    try {
      const d = await apiDocuments();
      setDocs(d.documents || []);
    } catch {
      /* best-effort */
    }
  }

  async function loadUploads() {
    // Best-effort secondary panel: on failure we just keep the empty-state message.
    try {
      const data = await apiUploadHistory();
      setUploads(data.history || []);
    } catch {
      setUploads([]);
    }
  }

  async function uploadFile(file) {
    if (!canAppend && !canReplace) {
      setUploadError("You are in read-only mode.");
      return;
    }
    if (!file) return;
    setUploadError("");
    setUpStatus("Classifying & analysing " + file.name + " \u2026");
    try {
      const data = await apiUpload(file, mode);
      setUpStatus("Analysed " + file.name);
      setResult(data);
      if (data.metrics) onAnalysed(data.metrics);
      if (canManageUsers) loadUploads();
    } catch (e) {
      setUpStatus("");
      setUploadError(e.message);
    }
  }

  async function uploadDocFile(file) {
    if (!canAppend && !canReplace) {
      setDocError("You are in read-only mode.");
      return;
    }
    if (!file) return;
    setDocError("");
    setDocStatus("Reading " + file.name + " \u2026");
    try {
      const data = await apiUploadDoc(file);
      const pages = data.summary.pages;
      setDocStatus("Indexed " + file.name + " (" + pages + " page" + (pages === 1 ? "" : "s") + ")");
      setDocs(data.documents || []);
    } catch (e) {
      setDocStatus("");
      setDocError(e.message);
    }
  }

  async function removeDoc(name) {
    if (!canAppend && !canReplace) {
      setDocError("You are in read-only mode.");
      return;
    }
    if (!window.confirm('Remove "' + name + '" from the indexed documents?')) return;
    setDocError("");
    try {
      const data = await apiRemoveDoc(name);
      setDocs(data.documents || []);
      setDocStatus("Removed " + name);
    } catch (e) {
      setDocError(e.message);
    }
  }

  async function loadUsers() {
    try {
      const data = await apiUsers();
      setUsers(data.users || []);
    } catch (e) {
      setUserError(e.message);
    }
  }

  async function createUser(e) {
    e.preventDefault();
    setUserError("");
    setUserStatus("");
    try {
      await apiCreateUser({ username: newUsername.trim(), password: newPassword, role: newRole });
      setUserStatus("User created.");
      setNewUsername("");
      setNewPassword("");
      setNewRole("worker");
      await loadUsers();
    } catch (err) {
      setUserError(err.message);
    }
  }

  async function changeRole(username, role) {
    setUserError("");
    try {
      await apiUpdateUserRole(username, role);
      setUserStatus("Role updated.");
      await loadUsers();
    } catch (err) {
      setUserError(err.message);
    }
  }

  async function deleteUserAccount(username) {
    if (!window.confirm('Delete user "' + username + '"?')) return;
    setUserError("");
    try {
      await apiDeleteUser(username);
      setUserStatus("User deleted.");
      await loadUsers();
    } catch (err) {
      setUserError(err.message);
    }
  }

  function dragProps(setDrag, onFile) {
    return {
      onDragOver: (e) => { e.preventDefault(); setDrag(true); },
      onDragEnter: (e) => { e.preventDefault(); setDrag(true); },
      onDragLeave: (e) => { e.preventDefault(); setDrag(false); },
      onDrop: (e) => {
        e.preventDefault();
        setDrag(false);
        if (e.dataTransfer.files.length) onFile(e.dataTransfer.files[0]);
      },
    };
  }

  const c = result && result.classification;
  const s = result && result.summary;
  const sample = result && result.sample;
  const message = result && result.message;

  return (
    <>
      {!canAppend && !canReplace && (
        <div className="card" style={{ marginBottom: "18px" }}>
          <h3 style={{ margin: 0, fontSize: "1rem" }}>Read-only access</h3>
          <p className="muted" style={{ margin: "8px 0 0" }}>
            Worker/Viewer users can view the dashboard and ask questions, but cannot upload or change data.
          </p>
        </div>
      )}
      <div className="card">
        <input
          type="file"
          ref={fileRef}
          accept=".csv,.tsv,.txt,.xlsx,.xlsm,.xls,.png,.jpg,.jpeg,.webp,.pdf"
          style={{ display: "none" }}
          onChange={(e) => e.target.files.length && uploadFile(e.target.files[0])}
        />
        <div
          className={"drop" + (dragSpend ? " drag" : "")}
          onClick={() => (canAppend || canReplace) && fileRef.current.click()}
          {...dragProps(setDragSpend, uploadFile)}
          style={{ opacity: canAppend || canReplace ? 1 : 0.6, pointerEvents: canAppend || canReplace ? "auto" : "none" }}
        >
          <div className="big">⬆️</div>
          <p><strong>Drop a spend file here</strong> or click to browse</p>
          <p className="muted">CSV, TSV, Excel — or a receipt / PDF. The agent detects the data type, then cleans it automatically.</p>
        </div>
        <div className="up-controls">
          <span className="muted">On upload:</span>
          <div className="seg">
            <button
              type="button"
              className={mode === "replace" ? "on" : ""}
              onClick={() => setMode("replace")}
              disabled={!canReplace}
              title={canReplace ? "" : "Only admins can replace the whole dataset"}
            >
              Replace dataset
            </button>
            <button
              type="button"
              className={mode === "append" ? "on" : ""}
              onClick={() => setMode("append")}
              disabled={!canAppend}
            >
              Add to dataset
            </button>
          </div>
          <span className="muted">{upStatus}</span>
        </div>
      </div>

      {canManageUsers && (
        <div className="card" style={{ marginTop: "18px" }}>
          <h3 style={{ margin: "0 0 12px", fontSize: "1rem" }}>Upload history</h3>
          {uploads.length === 0 ? (
            <p className="muted" style={{ margin: 0 }}>No uploads recorded yet.</p>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table>
                <tbody>
                  <tr>
                    <th>When</th><th>Who</th><th>File</th><th>Mode</th>
                    <th className="num">Rows added</th><th>Type</th>
                  </tr>
                  {uploads.map((u, i) => (
                    <tr key={i}>
                      <td>{new Date(u.ts).toLocaleString()}</td>
                      <td>{u.username}</td>
                      <td>{u.filename}</td>
                      <td>{u.mode}</td>
                      <td className="num">{num(u.rows_added)}</td>
                      <td>{u.is_spend ? (u.category || "spend") : (u.category || "non-spend")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      <div className="card" style={{ marginTop: "18px" }}>
        <h3 style={{ margin: "0 0 12px", fontSize: "1rem" }}>
          📄 Contracts &amp; policies <span className="muted" style={{ fontWeight: 400 }}>— lets answers cite your documents</span>
        </h3>
        <input
          type="file"
          ref={docFileRef}
          accept=".pdf,.docx,.docm,.txt"
          style={{ display: "none" }}
          onChange={(e) => e.target.files.length && uploadDocFile(e.target.files[0])}
        />
        <div
          className={"drop" + (dragDoc ? " drag" : "")}
          onClick={() => (canAppend || canReplace) && docFileRef.current.click()}
          {...dragProps(setDragDoc, uploadDocFile)}
          style={{ padding: "26px", opacity: canAppend || canReplace ? 1 : 0.6, pointerEvents: canAppend || canReplace ? "auto" : "none" }}
        >
          <div className="big">📄</div>
          <p><strong>Drop a contract or policy</strong> or click to browse</p>
          <p className="muted">PDF, Word or text — the agent reads it and cites it when you ask.</p>
        </div>
        <div className="up-controls"><span className="muted">{docStatus}</span></div>
        <div className="chips-in" style={{ marginTop: "12px" }}>
          {docs.map((d) => (
            <span className="tag doc-chip" key={d.document}>
              📄 {d.document} <b>· {d.chunks} chunks</b>
              <button type="button" className="doc-remove" title="Remove this document" onClick={() => removeDoc(d.document)}>✕</button>
            </span>
          ))}
        </div>
        {docError && <div className="dash-error" style={{ display: "block" }}>{docError}</div>}
      </div>

      {canManageUsers && (
        <div className="card" style={{ marginTop: "18px" }}>
          <h3 style={{ margin: "0 0 12px", fontSize: "1rem" }}>User management</h3>
          <form className="up-controls" onSubmit={createUser}>
            <input
              type="text"
              placeholder="username"
              value={newUsername}
              onChange={(e) => setNewUsername(e.target.value)}
              style={{ width: "180px" }}
            />
            <input
              type="text"
              placeholder="password (min 6 chars)"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              style={{ width: "220px" }}
            />
            <select value={newRole} onChange={(e) => setNewRole(e.target.value)} style={{ height: "42px", borderRadius: 10, border: "1px solid var(--border)", padding: "0 10px" }}>
              <option value="worker">worker/viewer</option>
              <option value="admin">admin</option>
            </select>
            <button type="submit" className="btn">Create user</button>
          </form>
          {userStatus && <div className="status" style={{ display: "block" }}>{userStatus}</div>}
          <div style={{ overflowX: "auto", marginTop: 12 }}>
            <table>
              <tbody>
                <tr><th>User</th><th>Role</th><th>Actions</th></tr>
                {users.map((u) => (
                  <tr key={u.username}>
                    <td>{u.username}</td>
                    <td>{u.role}</td>
                    <td>
                      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                        <select
                          value={u.role}
                          onChange={(e) => changeRole(u.username, e.target.value)}
                          style={{ height: "34px", borderRadius: 8, border: "1px solid var(--border)", padding: "0 8px" }}
                        >
                          <option value="worker">worker/viewer</option>
                          <option value="admin">admin</option>
                        </select>
                        <button type="button" className="chip" onClick={() => deleteUserAccount(u.username)}>Delete</button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {userError && <div className="dash-error" style={{ display: "block" }}>{userError}</div>}
        </div>
      )}

      {uploadError && <div className="dash-error" style={{ display: "block" }}>{uploadError}</div>}

      {result && (
        <div>
          {c && (
            <div className="card">
              <h3>🤖 Detected data type</h3>
              <div style={{ fontSize: "1.4rem", fontWeight: 750, marginBottom: "8px", letterSpacing: "-.01em" }}>
                {c.category || "Unknown"}
              </div>
              <div className="chips-in">
                {c.method && <span className="badge">{c.method}</span>}
                {c.confidence != null && <span className="tag">confidence {Math.round(c.confidence * 100)}%</span>}
                <span className="tag">{c.is_spend ? "analysable as spend" : "not spend data"}</span>
                {c.row_count ? <span className="tag">{Number(c.row_count).toLocaleString()} rows</span> : null}
              </div>
              <p className="muted" style={{ marginTop: "12px", lineHeight: 1.55 }}>{c.rationale || ""}</p>
              {message && <div className="muted" style={{ marginTop: "6px" }}>{message}</div>}
            </div>
          )}

          {s && (
            <div className="panel" style={{ marginTop: "18px" }}>
              <h3>🧹 Data cleaning summary <span className="badge">{s.mapping_method || ""}</span></h3>
              <div className="chips-in">
                {[
                  ["Rows read", num(s.rows_read)],
                  ["Rows loaded", num(s.rows_loaded)],
                  ["Rows skipped", num(s.rows_skipped)],
                  ["New suppliers", num(s.new_suppliers)],
                  ["New categories", num(s.new_categories)],
                  ["Total in model", num(s.total_rows_in_db)],
                ].map(([k, v]) => (
                  <span className="tag" key={k}>{k}: <b>{v}</b></span>
                ))}
              </div>
              <div style={{ overflowX: "auto" }}>
                <MapTable map={s.columns_mapped} />
              </div>
              <ul className="notes">{(s.notes || []).map((n, i) => <li key={i}>{n}</li>)}</ul>
            </div>
          )}

          {sample && sample.length > 0 && (
            <div className="panel" style={{ marginTop: "18px" }}>
              <h3>Cleaned data preview <span className="muted">· top 25 lines by amount</span></h3>
              <div style={{ overflowX: "auto" }}><PreviewTable sample={sample} /></div>
            </div>
          )}

          <div style={{ marginTop: "18px" }}>
            {result.metrics && (
              <button type="button" className="btn" onClick={onViewDashboard}>View dashboard →</button>
            )}
          </div>
        </div>
      )}
    </>
  );
}

function MapTable({ map }) {
  const keys = Object.keys(map || {});
  if (!keys.length) return <table />;
  return (
    <table>
      <tbody>
        <tr><th>Canonical field</th><th>Detected column</th></tr>
        {keys.map((k) => (
          <tr key={k}><td>{k}</td><td>{map[k]}</td></tr>
        ))}
      </tbody>
    </table>
  );
}

function PreviewTable({ sample }) {
  const cols = Object.keys(sample[0]);
  return (
    <table>
      <tbody>
        <tr>{cols.map((c) => <th key={c}>{c}</th>)}</tr>
        {sample.map((row, i) => (
          <tr key={i}>
            {cols.map((c) => {
              let v = row[c];
              if (c === "amount" || c === "unit_price") v = v == null ? "—" : moneyFull(v);
              else if (v === null || v === undefined) v = "—";
              else if (typeof v === "boolean") v = v ? "yes" : "no";
              const cls = c === "amount" || c === "unit_price" || c === "qty" ? "num" : undefined;
              return <td key={c} className={cls}>{v}</td>;
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
