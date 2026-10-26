import React from "react";

const NAV = [
  {
    view: "dash",
    label: "Dashboard",
    icon: (
      <>
        <path d="M3 3v18h18" />
        <rect x="7" y="11" width="3" height="7" rx="1" />
        <rect x="12" y="7" width="3" height="11" rx="1" />
        <rect x="17" y="4" width="3" height="14" rx="1" />
      </>
    ),
  },
  {
    view: "ask",
    label: "Ask",
    icon: <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />,
  },
  {
    view: "savings",
    label: "Savings",
    icon: (
      <>
        <line x1="12" y1="1" x2="12" y2="23" />
        <path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
      </>
    ),
  },
  {
    view: "upload",
    label: "Upload",
    icon: (
      <>
        <path d="M12 16V4" />
        <path d="m7 9 5-5 5 5" />
        <path d="M5 20h14" />
      </>
    ),
  },
];

export default function Sidebar({ view, onNavigate, user }) {
  const role = (user && user.role) || "worker";
  const canUpload = role === "admin";
  const navItems = canUpload ? NAV : NAV.filter((n) => n.view !== "upload");

  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark">
          <svg viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" width="22" height="22">
            <path d="M4 4v16h16" />
            <path d="M7 14l3-3 3 3 4-5" />
          </svg>
        </div>
        <div>
          <div className="brand-name">Spend Analytics</div>
          <div className="brand-sub">Agent</div>
        </div>
      </div>

      <div className="nav-label">Workspace</div>
      <nav className="nav">
        {navItems.map((n) => (
          <button
            key={n.view}
            type="button"
            className={"nav-item" + (view === n.view ? " active" : "")}
            onClick={() => onNavigate(n.view)}
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              {n.icon}
            </svg>
            <span className="lbl">{n.label}</span>
          </button>
        ))}
      </nav>
    </aside>
  );
}
