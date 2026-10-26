// Thin wrappers around the FastAPI endpoints. All URLs are same-origin relative,
// which works both in production (FastAPI serves the built app) and in dev
// (Vite proxies these routes to the backend — see vite.config.js).

async function jsonOrThrow(response) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && /invalid session|session expired/i.test(data.detail || "")) {
      setAuthToken("");
    }
    throw new Error(data.detail || `Request failed (${response.status})`);
  }
  return data;
}

let authToken = window.localStorage.getItem("spend_auth_token") || "";

export function setAuthToken(token) {
  authToken = token || "";
  if (authToken) window.localStorage.setItem("spend_auth_token", authToken);
  else window.localStorage.removeItem("spend_auth_token");
  window.dispatchEvent(new CustomEvent("spend-auth-changed", { detail: { token: authToken } }));
}

function authHeaders(extra = {}) {
  return authToken ? { ...extra, Authorization: `Bearer ${authToken}` } : extra;
}

export async function apiAsk(q) {
  return jsonOrThrow(
    await fetch("/ask", {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ q }),
    })
  );
}

export async function apiMetrics(range) {
  const qs = new URLSearchParams();
  if (range && range.start_date) qs.set("start_date", range.start_date);
  if (range && range.end_date) qs.set("end_date", range.end_date);
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return jsonOrThrow(await fetch(`/metrics${suffix}`, { headers: authHeaders() }));
}

export async function apiBreakdown(dim, value) {
  return jsonOrThrow(
    await fetch(`/breakdown?dim=${encodeURIComponent(dim)}&value=${encodeURIComponent(value)}`, {
      headers: authHeaders(),
    })
  );
}

export async function apiLines(dim, value, item) {
  return jsonOrThrow(
    await fetch(
      `/lines?dim=${encodeURIComponent(dim)}&value=${encodeURIComponent(value)}&item=${encodeURIComponent(item)}`,
      { headers: authHeaders() }
    )
  );
}

export async function apiUpload(file, mode) {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("mode", mode);
  return jsonOrThrow(await fetch("/upload", { method: "POST", headers: authHeaders(), body: fd }));
}

export async function apiDocuments() {
  return jsonOrThrow(await fetch("/documents", { headers: authHeaders() }));
}

export async function apiUploadDoc(file) {
  const fd = new FormData();
  fd.append("file", file);
  return jsonOrThrow(await fetch("/upload-doc", { method: "POST", headers: authHeaders(), body: fd }));
}

export async function apiRemoveDoc(name) {
  return jsonOrThrow(
    await fetch(`/documents?name=${encodeURIComponent(name)}`, { method: "DELETE", headers: authHeaders() })
  );
}

export async function apiUploadHistory() {
  return jsonOrThrow(await fetch("/upload-history", { headers: authHeaders() }));
}

// --- Savings realisation tracker ---
export async function apiSavings() {
  return jsonOrThrow(await fetch("/savings", { headers: authHeaders() }));
}

export async function apiSavingsSuggestions() {
  return jsonOrThrow(await fetch("/savings/opportunities", { headers: authHeaders() }));
}

export async function apiSavingsCreate(body) {
  return jsonOrThrow(
    await fetch("/savings", {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(body),
    })
  );
}

export async function apiSavingsUpdate(id, patch) {
  return jsonOrThrow(
    await fetch(`/savings/${id}`, {
      method: "PATCH",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(patch),
    })
  );
}

export async function apiSavingsDelete(id) {
  return jsonOrThrow(await fetch(`/savings/${id}`, { method: "DELETE", headers: authHeaders() }));
}

// --- Authentication ---
export async function apiLogin(username, password) {
  const data = await jsonOrThrow(
    await fetch("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    })
  );
  setAuthToken(data.token || "");
  return data;
}

export async function apiMe() {
  return jsonOrThrow(await fetch("/auth/me", { headers: authHeaders() }));
}

export async function apiLogout() {
  const out = await jsonOrThrow(await fetch("/auth/logout", { method: "POST", headers: authHeaders() }));
  setAuthToken("");
  return out;
}

// --- Admin user management ---
export async function apiUsers() {
  return jsonOrThrow(await fetch("/auth/users", { headers: authHeaders() }));
}

export async function apiCreateUser(body) {
  return jsonOrThrow(
    await fetch("/auth/users", {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(body),
    })
  );
}

export async function apiUpdateUserRole(username, role) {
  return jsonOrThrow(
    await fetch(`/auth/users/${encodeURIComponent(username)}/role`, {
      method: "PATCH",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ role }),
    })
  );
}

export async function apiDeleteUser(username) {
  return jsonOrThrow(
    await fetch(`/auth/users/${encodeURIComponent(username)}`, {
      method: "DELETE",
      headers: authHeaders(),
    })
  );
}
