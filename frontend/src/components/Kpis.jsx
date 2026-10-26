import React from "react";
import { money, moneyFull, num, pct } from "../format.js";

// Helper SVG icons for KPI Cards
const KPI_ICONS = {
  spend: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <line x1="12" y1="1" x2="12" y2="23" />
      <path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
    </svg>
  ),
  avg: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="4" y="4" width="16" height="16" rx="2" />
      <line x1="8" y1="12" x2="16" y2="12" />
      <line x1="12" y1="8" x2="12" y2="16" />
    </svg>
  ),
  suppliers: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
      <path d="M16 3.13a4 4 0 0 1 0 7.75" />
    </svg>
  ),
  categories: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
    </svg>
  ),
  maverick: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
      <line x1="12" y1="9" x2="12" y2="13" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  ),
  tail: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
    </svg>
  ),
  top5: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M21.21 15.89A10 10 0 1 1 8 2.83" />
      <path d="M22 12A10 10 0 0 0 12 2v10z" />
    </svg>
  ),
  leak: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="10" />
      <line x1="15" y1="9" x2="9" y2="15" />
      <line x1="9" y1="9" x2="15" y2="15" />
    </svg>
  ),
  compliant: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
      <polyline points="9 12 11 14 15 10" />
    </svg>
  ),
  avgSupplier: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="2" y="7" width="20" height="14" rx="2" ry="2" />
      <path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16" />
    </svg>
  ),
};

function buildCards(m) {
  const t = m.totals || {};
  const total = Number(t.total_spend) || 0;
  const tail = m.tail || {};
  const sup = m.top_suppliers || [];
  const leak = Number((m.overpayments || {}).total) || 0;

  const cards = [
    {
      id: "spend",
      icon: KPI_ICONS.spend,
      label: "Total spend",
      value: money(t.total_spend),
      sub: moneyFull(t.total_spend),
      tip: "Sum of every spend line amount in the current dataset.",
      accent: "indigo",
    },
  ];

  if (t.lines) {
    cards.push({
      id: "avg",
      icon: KPI_ICONS.avg,
      label: "Avg line value",
      value: money(total / t.lines),
      sub: num(t.lines) + " spend lines",
      tip: "Average amount per spend line — total spend divided by line count.",
      accent: "indigo",
    });
  }

  cards.push({
    id: "suppliers",
    icon: KPI_ICONS.suppliers,
    label: "Suppliers",
    value: num(t.suppliers),
    sub: "Active supply base",
    tip: "Number of distinct suppliers in the dataset.",
    accent: "emerald",
  });

  cards.push({
    id: "categories",
    icon: KPI_ICONS.categories,
    label: "Categories",
    value: num(t.categories),
    sub: "Spend classifications",
    tip: "Number of distinct spend categories.",
    accent: "purple",
  });

  if (t.maverick_amount != null) {
    const mavRatio = total ? (t.maverick_amount / total) : 0;
    cards.push({
      id: "maverick",
      icon: KPI_ICONS.maverick,
      label: "Maverick spend",
      value: money(t.maverick_amount),
      sub: pct(t.maverick_pct || 0) + " of total",
      progress: mavRatio,
      isDanger: mavRatio > 0.15,
      tip: "Spend made outside preferred suppliers or agreed contracts.",
      accent: "amber",
    });
  }

  if (tail.spend != null && total) {
    const tailRatio = tail.spend / total;
    cards.push({
      id: "tail",
      icon: KPI_ICONS.tail,
      label: "Tail spend",
      value: money(tail.spend),
      sub: pct(tailRatio) + " · " + num(tail.supplier_count) + " suppliers",
      progress: tailRatio,
      tip: "The long tail of small suppliers making up the last ~20% of spend.",
      accent: "cyan",
    });
  }

  if (sup.length && total) {
    const top5 = sup.slice(0, 5).reduce((a, r) => a + (Number(r.spend) || 0), 0);
    const top5Ratio = top5 / total;
    cards.push({
      id: "top5",
      icon: KPI_ICONS.top5,
      label: "Top-5 concentration",
      value: pct(top5Ratio),
      sub: money(top5) + " top spend",
      progress: top5Ratio,
      tip: "Share of total spend going to your five largest suppliers.",
      accent: "blue",
    });
  }

  cards.push({
    id: "leak",
    icon: KPI_ICONS.leak,
    label: "Contract leakage",
    value: money(leak),
    sub: leak > 0 ? "overpaid vs contract" : "no price leakage",
    isDanger: leak > 0,
    tip: "Amount paid above agreed contract prices.",
    accent: "rose",
  });

  const onContract = total - (t.maverick_amount || 0);
  const compliantRatio = total ? onContract / total : 0;
  cards.push({
    id: "compliant",
    icon: KPI_ICONS.compliant,
    label: "On-contract spend",
    value: money(onContract),
    sub: pct(compliantRatio) + " compliant",
    progress: compliantRatio,
    tip: "Total spend managed under active contracts or preferred suppliers.",
    accent: "emerald",
  });

  const avgSupplier = t.suppliers ? total / t.suppliers : 0;
  cards.push({
    id: "avgSupplier",
    icon: KPI_ICONS.avgSupplier,
    label: "Avg spend / supplier",
    value: money(avgSupplier),
    sub: "across " + num(t.suppliers) + " suppliers",
    tip: "Average spend volume per active supplier across the supply base.",
    accent: "violet",
  });

  return cards;
}

export default function Kpis({ metrics }) {
  const cards = buildCards(metrics || {});
  return (
    <div className="kpis-grid">
      {cards.map((c, i) => (
        <div
          className={`kpi-card accent-${c.accent}${c.isDanger ? " danger-kpi" : ""}`}
          key={i}
          {...(c.tip ? { "data-tip": c.tip } : {})}
        >
          <div className="kpi-head">
            <div className="kpi-icon-badge">{c.icon}</div>
            <div className="kpi-label">{c.label}</div>
            {c.tip && <span className="kpi-info-trigger">i</span>}
          </div>
          <div className="kpi-value">{c.value}</div>
          <div className="kpi-sub">{c.sub || ""}</div>

          {c.progress !== undefined && (
            <div className="kpi-mini-progress-track">
              <div
                className={`kpi-mini-progress-fill${c.isDanger ? " fill-danger" : ""}`}
                style={{ width: `${Math.min(100, Math.max(2, c.progress * 100))}%` }}
              />
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
