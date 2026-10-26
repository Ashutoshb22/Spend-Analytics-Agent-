import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  apiSavings,
  apiSavingsSuggestions,
  apiSavingsCreate,
  apiSavingsUpdate,
  apiSavingsDelete,
} from "../api.js";
import { money, moneyFull } from "../format.js";

// The savings lifecycle, in order. "realised" is terminal.
const FLOW = ["identified", "negotiating", "contracted", "realised"];
const LABELS = {
  identified: "Identified",
  negotiating: "In negotiation",
  contracted: "Contracted",
  realised: "Realised",
};

// Detection types -> short display labels.
const KIND = {
  consolidation: "Consolidation",
  price_variance: "Price variance",
  maverick: "Off-contract",
  tail: "Long-tail",
  low_value: "Low-value POs",
  overpayment: "Contract leakage",
  custom: "Custom",
};
const kindLabel = (k) => KIND[k] || k;

const statusRank = (o) => (o._suggested ? -1 : FLOW.indexOf(o.status));
const SORTS = {
  target: { label: "Biggest target", fn: (a, b) => (b.target_annual || 0) - (a.target_annual || 0) },
  realised: { label: "Most realised", fn: (a, b) => (b.realised || 0) - (a.realised || 0) },
  type: { label: "Type", fn: (a, b) => kindLabel(a.kind).localeCompare(kindLabel(b.kind)) },
  stage: { label: "Stage", fn: (a, b) => statusRank(a) - statusRank(b) },
};

// Shorten a title for use inside toast messages.
const short = (t) => (t && t.length > 30 ? t.slice(0, 30).trimEnd() + "\u2026" : t || "");

export default function Savings({ active }) {
  const [data, setData] = useState(null); // { opportunities, rollup }
  const [suggestions, setSuggestions] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState({}); // id -> true while a request is in flight
  const [adding, setAdding] = useState(false);
  const [toasts, setToasts] = useState([]); // transient success / error messages

  // View + filter/sort controls.
  const [view, setView] = useState("list"); // "list" | "board"
  const [q, setQ] = useState("");
  const [kindFilter, setKindFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [sort, setSort] = useState("target");

  const pushToast = useCallback((msg, type = "ok") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, msg, type }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 3400);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [board, sug] = await Promise.all([apiSavings(), apiSavingsSuggestions()]);
      setData(board);
      setSuggestions(sug.suggestions || []);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  // Refresh each time the tab is opened (so new uploads surface fresh opportunities).
  useEffect(() => {
    if (active) load();
  }, [active, load]);

  // Run a mutating action with a per-id busy flag, a reload, and a toast on finish.
  const run = useCallback(
    async (id, fn, okMsg) => {
      setBusy((b) => ({ ...b, [id]: true }));
      try {
        await fn();
        await load();
        if (okMsg) pushToast(okMsg, "ok");
      } catch (e) {
        pushToast(e.message, "error");
      } finally {
        setBusy((b) => {
          const next = { ...b };
          delete next[id];
          return next;
        });
      }
    },
    [load, pushToast]
  );

  const move = (opp, dir) => {
    const next = FLOW[FLOW.indexOf(opp.status) + dir];
    if (!next) return;
    run(opp.id, () => apiSavingsUpdate(opp.id, { status: next }), `${short(opp.title)} \u2192 ${LABELS[next]}`);
  };

  const remove = (opp) => run(opp.id, () => apiSavingsDelete(opp.id), `Removed \u201c${short(opp.title)}\u201d`);

  const fromSuggestion = (sug, extra) => ({
    title: sug.title,
    kind: sug.kind,
    category: sug.category ?? null,
    supplier: sug.supplier ?? null,
    item: sug.item ?? null,
    target_annual: sug.target_annual,
    rationale: sug.rationale,
    source: "auto",
    ...extra,
  });

  const track = (sug) =>
    run(`sug:${sug.title}`, () => apiSavingsCreate(fromSuggestion(sug)), `Now tracking \u201c${short(sug.title)}\u201d`);

  const dismiss = (sug) =>
    run(`sug:${sug.title}`, () => apiSavingsCreate(fromSuggestion(sug, { status: "dismissed" })), "Suggestion dismissed");

  // Unified rows: agent suggestions (status "suggested") + tracked opportunities.
  const allRows = useMemo(() => {
    const sug = suggestions.map((s) => ({
      ...s, _suggested: true, status: "suggested", id: `sug:${s.title}`, realised: 0,
    }));
    return [...(data?.opportunities || []), ...sug];
  }, [data, suggestions]);

  const kindsPresent = useMemo(() => {
    const present = new Set(allRows.map((o) => o.kind));
    return Object.keys(KIND).filter((k) => present.has(k));
  }, [allRows]);

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const rows = allRows.filter((o) => {
      if (kindFilter !== "all" && o.kind !== kindFilter) return false;
      if (statusFilter !== "all" && o.status !== statusFilter) return false;
      if (needle) {
        const hay = `${o.title} ${o.category || ""} ${o.supplier || ""} ${o.item || ""}`.toLowerCase();
        if (!hay.includes(needle)) return false;
      }
      return true;
    });
    return rows.slice().sort(SORTS[sort].fn);
  }, [allRows, q, kindFilter, statusFilter, sort]);

  const byStatus = useMemo(() => {
    const groups = { identified: [], negotiating: [], contracted: [], realised: [] };
    (data?.opportunities || []).forEach((o) => {
      if (groups[o.status]) groups[o.status].push(o);
    });
    return groups;
  }, [data]);

  const rollup = data?.rollup;
  // "Potential" = everything still open: tracked-but-not-realised targets + all suggestions.
  const potential = useMemo(() => {
    const openTracked = (data?.opportunities || [])
      .filter((o) => o.status !== "realised")
      .reduce((a, o) => a + (o.target_annual || 0), 0);
    const sug = suggestions.reduce((a, s) => a + (s.target_annual || 0), 0);
    return openTracked + sug;
  }, [data, suggestions]);

  const isEmpty = data && allRows.length === 0;

  return (
    <>
      {error && <div className="dash-error" style={{ display: "block" }}>{error}</div>}

      {rollup && <Header potential={potential} rollup={rollup} suggestions={suggestions.length} />}

      <Toolbar
        view={view}
        setView={setView}
        q={q}
        setQ={setQ}
        kindFilter={kindFilter}
        setKindFilter={setKindFilter}
        kindsPresent={kindsPresent}
        statusFilter={statusFilter}
        setStatusFilter={setStatusFilter}
        sort={sort}
        setSort={setSort}
        adding={adding}
        onAddToggle={() => setAdding((v) => !v)}
      />

      {adding && (
        <AddForm
          onCancel={() => setAdding(false)}
          onCreate={async (body) => {
            await run("new", () => apiSavingsCreate(body), `Added \u201c${short(body.title)}\u201d`);
            setAdding(false);
          }}
        />
      )}

      {isEmpty && !adding && (
        <div className="panel sv-empty">
          <div className="sv-empty-mark">$</div>
          <div>
            <strong>No savings to track yet.</strong>
            <p className="muted">
              When the agent spots opportunities in your spend — fragmented categories, price
              variance, off-contract buys and more — they appear here to track from idea to
              realised savings. Upload richer spend data, or add one manually above.
            </p>
          </div>
        </div>
      )}

      {!isEmpty && view === "list" && (
        <OppList
          rows={filtered}
          total={allRows.length}
          busy={busy}
          onTrack={track}
          onDismiss={dismiss}
          onAdvance={(o) => move(o, +1)}
          onBack={(o) => move(o, -1)}
          onRemove={remove}
        />
      )}

      {!isEmpty && view === "board" && (
        <>
          <p className="muted sv-board-sub" style={{ margin: "4px 2px 12px" }}>
            The board shows tracked opportunities. Switch to List to review the {suggestions.length}{" "}
            agent suggestion{suggestions.length === 1 ? "" : "s"}.
          </p>
          <div className="sv-board">
            {FLOW.map((status) => (
              <Column
                key={status}
                status={status}
                items={byStatus[status]}
                busy={busy}
                onAdvance={(o) => move(o, +1)}
                onBack={(o) => move(o, -1)}
                onRemove={remove}
              />
            ))}
          </div>
        </>
      )}

      {loading && !data && <div className="muted-center">Loading savings…</div>}

      <div className="sv-toasts" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`sv-toast ${t.type}`}>
            <span className="sv-toast-ico">{t.type === "error" ? "!" : "\u2713"}</span>
            <span>{t.msg}</span>
          </div>
        ))}
      </div>
    </>
  );
}

// ------------------------------------------------------------------ header
function Header({ potential, rollup }) {
  return (
    <div className="sv-hero">
      <div className="sv-hero-main">
        <div className="sv-hero-fig sv-hero-potential">
          <div className="label">Total potential savings</div>
          <div className="value" title={moneyFull(potential) + " / yr"}>{money(potential)}<span>/yr</span></div>
          <div className="sub">across every open opportunity</div>
        </div>
        <div className="sv-hero-fig sv-hero-realised">
          <div className="label">Realised so far</div>
          <div className="value" title={moneyFull(rollup.realised)}>{money(rollup.realised)}</div>
          <div className="sub">measured from the ledger</div>
        </div>
      </div>
      <div className="sv-stagebar">
        {FLOW.map((s) => (
          <div className={`sv-stagechip sv-stage-${s}`} key={s}>
            <span className="dot" />
            <span className="nm">{LABELS[s]}</span>
            <span className="amt">{money(rollup[s] ?? rollup.realised)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ toolbar
function Toolbar({
  view, setView, q, setQ, kindFilter, setKindFilter, kindsPresent,
  statusFilter, setStatusFilter, sort, setSort, adding, onAddToggle,
}) {
  return (
    <div className="sv-toolbar">
      <div className="sv-search">
        <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <circle cx="11" cy="11" r="7" />
          <path d="m21 21-4.3-4.3" />
        </svg>
        <input
          type="text"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search opportunities, categories, suppliers, items…"
        />
      </div>

      <select className="sv-select" value={kindFilter} onChange={(e) => setKindFilter(e.target.value)} title="Filter by type">
        <option value="all">All types</option>
        {kindsPresent.map((k) => (
          <option key={k} value={k}>{kindLabel(k)}</option>
        ))}
      </select>

      <select className="sv-select" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} title="Filter by stage">
        <option value="all">All stages</option>
        <option value="suggested">Suggested</option>
        {FLOW.map((s) => (
          <option key={s} value={s}>{LABELS[s]}</option>
        ))}
      </select>

      <select className="sv-select" value={sort} onChange={(e) => setSort(e.target.value)} title="Sort by">
        {Object.entries(SORTS).map(([k, s]) => (
          <option key={k} value={k}>Sort: {s.label}</option>
        ))}
      </select>

      <div className="sv-viewtoggle" role="tablist">
        <button type="button" className={view === "list" ? "on" : ""} onClick={() => setView("list")}>List</button>
        <button type="button" className={view === "board" ? "on" : ""} onClick={() => setView("board")}>Board</button>
      </div>

      <button type="button" className="sv-add-btn" onClick={onAddToggle}>
        {adding ? "Cancel" : "+ New"}
      </button>
    </div>
  );
}

// ------------------------------------------------------------------ list view (grouped by type)

// Preferred display order for opportunity kinds
const KIND_ORDER = ["price_variance", "maverick", "consolidation", "tail", "low_value", "overpayment", "custom"];

function OppList({ rows, total, busy, onTrack, onDismiss, onAdvance, onBack, onRemove }) {
  // Group rows by kind
  const groups = useMemo(() => {
    const map = {};
    rows.forEach((r) => {
      if (!map[r.kind]) map[r.kind] = [];
      map[r.kind].push(r);
    });
    // Sort groups by the defined KIND_ORDER, unknown kinds at the end
    return Object.entries(map).sort(([a], [b]) => {
      const ia = KIND_ORDER.indexOf(a);
      const ib = KIND_ORDER.indexOf(b);
      return (ia === -1 ? 999 : ia) - (ib === -1 ? 999 : ib);
    });
  }, [rows]);

  if (rows.length === 0) {
    return (
      <div className="sv-list">
        <div className="muted-center">No opportunities match your filters.</div>
      </div>
    );
  }

  return (
    <div className="sv-grouped">
      {groups.map(([kind, items]) => (
        <KindSection
          key={kind}
          kind={kind}
          items={items}
          busy={busy}
          onTrack={onTrack}
          onDismiss={onDismiss}
          onAdvance={onAdvance}
          onBack={onBack}
          onRemove={onRemove}
        />
      ))}
      <div className="sv-grouped-foot">{rows.length} of {total} opportunities shown</div>
    </div>
  );
}

// A collapsible section for a single opportunity type
function KindSection({ kind, items, busy, onTrack, onDismiss, onAdvance, onBack, onRemove }) {
  const [collapsed, setCollapsed] = useState(false);
  const groupTotal = items.reduce((a, o) => a + (o.target_annual || 0), 0);

  // Count items by status for the summary chips
  const statusCounts = useMemo(() => {
    const counts = {};
    items.forEach((o) => {
      const s = o._suggested ? "suggested" : o.status;
      counts[s] = (counts[s] || 0) + 1;
    });
    return counts;
  }, [items]);

  return (
    <div className={`sv-kind-section sv-kind-section-${kind}`}>
      <button
        type="button"
        className="sv-kind-section-head"
        onClick={() => setCollapsed((v) => !v)}
        aria-expanded={!collapsed}
      >
        <span className={`sv-kind sv-kind-${kind}`}>{kindLabel(kind)}</span>
        <span className="sv-kind-section-count">{items.length} opportunit{items.length === 1 ? "y" : "ies"}</span>
        <span className="sv-kind-section-summary">
          {Object.entries(statusCounts).map(([s, n]) => (
            <span key={s} className={`sv-mini-pill sv-mini-pill-${s}`}>{n} {s === "suggested" ? "Suggested" : LABELS[s] || s}</span>
          ))}
        </span>
        <span className="sv-kind-section-target">{money(groupTotal)}<span>/yr</span></span>
        <span className={`sv-kind-section-chev${collapsed ? " collapsed" : ""}`}>▾</span>
      </button>

      {!collapsed && (
        <div className="sv-list">
          <div className="sv-list-head">
            <span>Opportunity</span>
            <span className="num">Target / yr</span>
            <span>Stage</span>
            <span className="sv-list-act">Actions</span>
          </div>
          {items.map((row) => (
            <ListRow
              key={row.id}
              row={row}
              busy={!!busy[row.id]}
              onTrack={onTrack}
              onDismiss={onDismiss}
              onAdvance={onAdvance}
              onBack={onBack}
              onRemove={onRemove}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function ListRow({ row, busy, onTrack, onDismiss, onAdvance, onBack, onRemove }) {
  const [open, setOpen] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const suggested = row._suggested;
  const idx = FLOW.indexOf(row.status);
  const realising = row.status === "contracted" || row.status === "realised";
  const pct = row.pct_to_target != null ? Math.round(row.pct_to_target * 100) : null;
  const chips = [row.category, row.supplier, row.item].filter(Boolean);

  return (
    <div className={`sv-row${busy ? " busy" : ""}`}>
      <div className="sv-row-main">
        <div className="sv-row-top">
          <span className={`sv-kind sv-kind-${row.kind}`}>{kindLabel(row.kind)}</span>
          {row.rationale && (
            <button type="button" className="sv-row-title" onClick={() => setOpen((v) => !v)} title="Show why">
              {row.title} <span className="sv-row-chev">{open ? "\u25be" : "\u25b8"}</span>
            </button>
          )}
          {!row.rationale && <span className="sv-row-title as-text">{row.title}</span>}
        </div>
        {chips.length > 0 && (
          <div className="sv-chips">
            {chips.map((c, i) => <span className="sv-chip" key={i}>{c}</span>)}
          </div>
        )}
        {open && row.rationale && <p className="sv-why-text">{row.rationale}</p>}
      </div>

      <div className="sv-row-target num" title={moneyFull(row.target_annual) + " / yr"}>
        {money(row.target_annual)}
      </div>

      <div className="sv-row-stage">
        <span className={`sv-pill sv-pill-${suggested ? "suggested" : row.status}`}>
          {suggested ? "Suggested" : LABELS[row.status]}
        </span>
        {realising && row.baseline_date && (
          <div className="sv-rowprog" title={`Measured since ${String(row.baseline_date).slice(0, 10)}`}>
            <div className="sv-prog"><span className="sv-prog-fill" style={{ width: `${Math.min(pct || 0, 100)}%` }} /></div>
            <span className="sv-rowprog-txt"><strong>{money(row.realised)}</strong>{pct != null ? ` · ${pct}%` : ""}</span>
          </div>
        )}
      </div>

      <div className="sv-row-actions">
        {suggested ? (
          <>
            <button type="button" className="btn sv-mini" onClick={() => onTrack(row)} disabled={busy}>
              {busy ? "…" : "Track"}
            </button>
            <button type="button" className="sv-mini-ghost" onClick={() => onDismiss(row)} disabled={busy}>Dismiss</button>
          </>
        ) : confirming ? (
          <div className="sv-confirm">
            <span className="sv-confirm-q">Remove?</span>
            <button type="button" className="sv-confirm-yes" onClick={() => onRemove(row)} disabled={busy}>Yes</button>
            <button type="button" className="sv-confirm-no" onClick={() => setConfirming(false)} disabled={busy}>No</button>
          </div>
        ) : (
          <>
            <button
              type="button"
              className="sv-move"
              onClick={() => onBack(row)}
              disabled={idx <= 0 || busy}
              title={idx > 0 ? `Back to ${LABELS[FLOW[idx - 1]]}` : "First stage"}
              aria-label="Move back a stage"
            >
              ←
            </button>
            <button
              type="button"
              className="sv-move sv-move-fwd"
              onClick={() => onAdvance(row)}
              disabled={idx >= FLOW.length - 1 || busy}
              title={idx < FLOW.length - 1 ? `Advance to ${LABELS[FLOW[idx + 1]]}` : "Fully realised"}
            >
              {idx < FLOW.length - 1 ? "\u2192" : "\u2713"}
            </button>
            <button type="button" className="sv-x" title="Remove" aria-label="Remove" onClick={() => setConfirming(true)} disabled={busy}>
              ✕
            </button>
          </>
        )}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ board view (kanban)
function Column({ status, items, busy, onAdvance, onBack, onRemove }) {
  const total = items.reduce((a, o) => a + (o.target_annual || 0), 0);
  return (
    <div className={`sv-col sv-col-${status}`}>
      <div className="sv-col-head">
        <span className="sv-col-name">{LABELS[status]}</span>
        <span className="sv-col-meta">{items.length} · {money(total)}</span>
      </div>
      <div className="sv-col-body">
        {items.length === 0 && <div className="sv-col-empty">Nothing here yet</div>}
        {items.map((o) => (
          <OppCard
            key={o.id}
            opp={o}
            busy={!!busy[o.id]}
            onAdvance={() => onAdvance(o)}
            onBack={() => onBack(o)}
            onRemove={() => onRemove(o)}
          />
        ))}
      </div>
    </div>
  );
}

function OppCard({ opp, busy, onAdvance, onBack, onRemove }) {
  const [confirming, setConfirming] = useState(false);
  const [showWhy, setShowWhy] = useState(false);
  const idx = FLOW.indexOf(opp.status);
  const canBack = idx > 0;
  const canAdvance = idx < FLOW.length - 1;
  const realising = opp.status === "contracted" || opp.status === "realised";
  const pct = opp.pct_to_target != null ? Math.round(opp.pct_to_target * 100) : null;
  const chips = [opp.category, opp.supplier, opp.item].filter(Boolean);
  const realisedTip =
    realising && opp.baseline_date
      ? `Measured since ${String(opp.baseline_date).slice(0, 10)}: cost at the old run-rate minus actual spend.`
      : "";
  return (
    <div className={`sv-card${busy ? " busy" : ""}`}>
      <div className="sv-card-top">
        <span className={`sv-kind sv-kind-${opp.kind}`}>{kindLabel(opp.kind)}</span>
        {!confirming && (
          <button type="button" className="sv-x" title="Remove" aria-label="Remove opportunity" onClick={() => setConfirming(true)} disabled={busy}>
            ✕
          </button>
        )}
      </div>
      <div className="sv-card-title">{opp.title}</div>

      <div className="sv-card-target">
        <span className="t-val" title={moneyFull(opp.target_annual) + " / yr"}>{money(opp.target_annual)}</span>
        <span className="t-lbl">/yr target</span>
      </div>

      {chips.length > 0 && (
        <div className="sv-chips">
          {chips.map((c, i) => <span className="sv-chip" key={i}>{c}</span>)}
        </div>
      )}

      {realising && opp.baseline_date && (
        <div className="sv-realised" title={realisedTip}>
          <div className="sv-prog">
            <span className="sv-prog-fill" style={{ width: `${Math.min(pct || 0, 100)}%` }} />
          </div>
          <div className="sv-realised-txt">
            <strong>{money(opp.realised)}</strong> realised
            {pct != null && <span className="muted"> · {pct}% of target</span>}
          </div>
        </div>
      )}

      {opp.rationale && (
        <button type="button" className="sv-why-toggle" onClick={() => setShowWhy((v) => !v)}>
          {showWhy ? "Hide details" : "Why this?"}
        </button>
      )}
      {showWhy && opp.rationale && <p className="sv-why-text">{opp.rationale}</p>}

      {opp.owner && <div className="sv-owner">Owner: {opp.owner}</div>}

      <StageDots status={opp.status} />

      {confirming ? (
        <div className="sv-confirm">
          <span className="sv-confirm-q">Remove this?</span>
          <button type="button" className="sv-confirm-yes" onClick={onRemove} disabled={busy}>Yes</button>
          <button type="button" className="sv-confirm-no" onClick={() => setConfirming(false)} disabled={busy}>No</button>
        </div>
      ) : (
        <div className="sv-actions">
          <button
            type="button"
            className="sv-move"
            onClick={onBack}
            disabled={!canBack || busy}
            title={canBack ? `Back to ${LABELS[FLOW[idx - 1]]}` : "Already at the first stage"}
            aria-label="Move back a stage"
          >
            ←
          </button>
          <button
            type="button"
            className="sv-move sv-move-fwd"
            onClick={onAdvance}
            disabled={!canAdvance || busy}
            title={canAdvance ? `Advance to ${LABELS[FLOW[idx + 1]]}` : "Fully realised"}
          >
            {canAdvance ? `${LABELS[FLOW[idx + 1]]} \u2192` : "Realised \u2713"}
          </button>
        </div>
      )}
    </div>
  );
}

function StageDots({ status }) {
  const idx = FLOW.indexOf(status);
  return (
    <div className="sv-steps" title={`Stage ${idx + 1} of ${FLOW.length}: ${LABELS[status]}`} aria-hidden="true">
      {FLOW.map((s, i) => (
        <span key={s} className={`sv-step${i < idx ? " done" : ""}${i === idx ? " cur" : ""}`} />
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ manual add
function AddForm({ onCreate, onCancel }) {
  const [title, setTitle] = useState("");
  const [target, setTarget] = useState("");
  const [category, setCategory] = useState("");
  const [supplier, setSupplier] = useState("");
  const [saving, setSaving] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (!title.trim()) return;
    setSaving(true);
    try {
      await onCreate({
        title: title.trim(),
        target_annual: target ? Number(target) : null,
        category: category.trim() || null,
        supplier: supplier.trim() || null,
        kind: "custom",
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <form className="panel sv-form" onSubmit={submit}>
      <div className="sv-form-grid">
        <label>
          <span>Title</span>
          <input type="text" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Renegotiate courier rates" autoFocus />
        </label>
        <label>
          <span>Annual target ($)</span>
          <input type="number" min="0" value={target} onChange={(e) => setTarget(e.target.value)} placeholder="40000" />
        </label>
        <label>
          <span>Category (optional)</span>
          <input type="text" value={category} onChange={(e) => setCategory(e.target.value)} placeholder="Freight &amp; Logistics" />
        </label>
        <label>
          <span>Supplier (optional)</span>
          <input type="text" value={supplier} onChange={(e) => setSupplier(e.target.value)} placeholder="DHL" />
        </label>
      </div>
      <div className="sv-form-actions">
        <button type="button" className="sv-add-btn" onClick={onCancel}>Cancel</button>
        <button type="submit" className="btn" disabled={saving || !title.trim()}>
          {saving ? "Adding…" : "Add to pipeline"}
        </button>
      </div>
    </form>
  );
}
