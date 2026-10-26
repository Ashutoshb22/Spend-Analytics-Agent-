import React, { useCallback, useEffect, useRef, useState } from "react";
import Sidebar from "./components/Sidebar.jsx";
import Dashboard from "./components/Dashboard.jsx";
import Ask from "./components/Ask.jsx";
import Savings from "./components/Savings.jsx";
import Upload from "./components/Upload.jsx";
import BreakdownModal from "./components/BreakdownModal.jsx";
import Login from "./components/Login.jsx";
import { apiLogout, apiMe, apiMetrics, setAuthToken } from "./api.js";

function UserProfileMenu({ user, onNavigate, onLogout }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    function handleClickOutside(e) {
      if (ref.current && !ref.current.contains(e.target)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const roleTitle = user.role === "admin" ? "Administrator" : "Procurement Worker";

  return (
    <div className="user-menu-container" ref={ref}>
      <button
        type="button"
        className={`user-menu-trigger${open ? " open" : ""}`}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        title="Account & Navigation"
      >
        <div className="user-avatar">
          {user.username.charAt(0).toUpperCase()}
        </div>
        <span className="user-menu-name">{user.username}</span>
        <span className="user-menu-chev">▾</span>
      </button>

      {open && (
        <div className="user-menu-dropdown">
          <div className="user-menu-header">
            <div className="user-menu-avatar-big">
              {user.username.charAt(0).toUpperCase()}
            </div>
            <div className="user-menu-meta">
              <div className="user-menu-full-name">{user.username}</div>
              <span className="user-menu-role-tag">{roleTitle}</span>
            </div>
          </div>

          <div className="user-menu-divider" />

          <div className="user-menu-section">
            <div className="user-menu-label">Quick Navigation</div>
            <button
              type="button"
              className="user-menu-item"
              onClick={() => { onNavigate("dash"); setOpen(false); }}
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="3" width="7" height="9" rx="1" />
                <rect x="14" y="3" width="7" height="5" rx="1" />
                <rect x="14" y="12" width="7" height="9" rx="1" />
                <rect x="3" y="16" width="7" height="5" rx="1" />
              </svg>
              <span>Dashboard Overview</span>
            </button>
            <button
              type="button"
              className="user-menu-item"
              onClick={() => { onNavigate("ask"); setOpen(false); }}
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
              </svg>
              <span>Ask Spend AI</span>
            </button>
            <button
              type="button"
              className="user-menu-item"
              onClick={() => { onNavigate("savings"); setOpen(false); }}
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="12" y1="1" x2="12" y2="23" />
                <path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
              </svg>
              <span>Savings Tracker</span>
            </button>
            <button
              type="button"
              className="user-menu-item"
              onClick={() => { onNavigate("upload"); setOpen(false); }}
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="17 8 12 3 7 8" />
                <line x1="12" y1="3" x2="12" y2="15" />
              </svg>
              <span>Upload Spend Data</span>
            </button>
          </div>

          <div className="user-menu-divider" />

          <button
            type="button"
            className="user-menu-item logout"
            onClick={() => { setOpen(false); onLogout(); }}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
              <polyline points="16 17 21 12 16 7" />
              <line x1="21" y1="12" x2="9" y2="12" />
            </svg>
            <span>Log out</span>
          </button>
        </div>
      )}
    </div>
  );
}

const TITLES = {
  dash: ["Dashboard", "Key metrics and trends across your spend data."],
  ask: ["Ask", "Query your spend in plain English \u2014 every answer is grounded in validated, read-only SQL."],
  savings: ["Savings tracker", "Follow every saving from idea to money in the bank \u2014 realised amounts are measured from the ledger."],
  upload: ["Upload", "Bring your own spend file \u2014 the agent classifies, cleans and analyses it."],
};

export default function App() {
  const [view, setView] = useState("dash");
  const [user, setUser] = useState(null);
  const [authReady, setAuthReady] = useState(false);
  const [metrics, setMetrics] = useState(null);
  const [metricsError, setMetricsError] = useState("");
  const [drill, setDrill] = useState(null); // { dim, value } for the breakdown modal
  const openBreakdown = useCallback((dim, value) => setDrill({ dim, value }), []);

  const loadMetrics = useCallback(async (range) => {
    try {
      setMetricsError("");
      setMetrics(await apiMetrics(range));
    } catch (e) {
      setMetricsError(e.message);
    }
  }, []);

  // Dashboard is the landing view, so load its metrics once on mount.
  useEffect(() => {
    async function boot() {
      try {
        const me = await apiMe();
        setUser(me);
        await loadMetrics();
      } catch (e) {
        setAuthToken("");
      } finally {
        setAuthReady(true);
      }
    }
    boot();
  }, [loadMetrics]);

  useEffect(() => {
    function handleAuthChanged(e) {
      if (e?.detail?.token) return;
      setUser(null);
      setMetrics(null);
      setMetricsError("");
      setView("dash");
    }

    window.addEventListener("spend-auth-changed", handleAuthChanged);
    return () => window.removeEventListener("spend-auth-changed", handleAuthChanged);
  }, []);

  async function onLoggedIn(me) {
    setUser(me);
    await loadMetrics();
  }

  async function onLogout() {
    try {
      await apiLogout();
    } catch {
      setAuthToken("");
    }
    setUser(null);
    setMetrics(null);
    setView("dash");
  }

  if (!authReady) {
    return <div className="auth-shell"><div className="muted">Loading...</div></div>;
  }

  if (!user) {
    return <Login onLoggedIn={onLoggedIn} />;
  }

  const [title, subtitle] = TITLES[view];
  const roleLabel = user.role === "worker" ? "worker/viewer" : user.role;

  return (
    <div className="app">
      <Sidebar view={view} onNavigate={setView} user={user} />
      <main className="content">
        <header className="topbar">
          <div className="topbar-row">
            <div>
              <h1>{title}</h1>
              <p>{subtitle}</p>
            </div>
            <div className="auth-meta">
              <UserProfileMenu user={user} onNavigate={setView} onLogout={onLogout} />
            </div>
          </div>
        </header>
        <div className="content-body">
          <section className={"view" + (view === "ask" ? " active" : "")}>
            <Ask user={user} />
          </section>
          <section className={"view" + (view === "dash" ? " active" : "")}>
            <Dashboard metrics={metrics} error={metricsError} onDrill={openBreakdown} onRangeChange={loadMetrics} />
          </section>
          <section className={"view" + (view === "savings" ? " active" : "")}>
            <Savings active={view === "savings"} />
          </section>
          <section className={"view" + (view === "upload" ? " active" : "")}>
            <Upload
              user={user}
              onAnalysed={(m) => { if (m) setMetrics(m); }}
              onViewDashboard={() => setView("dash")}
            />
          </section>
        </div>
      </main>
      <BreakdownModal drill={drill} onClose={() => setDrill(null)} />
    </div>
  );
}
