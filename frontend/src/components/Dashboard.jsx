import React, { useState, useMemo } from "react";
import Kpis from "./Kpis.jsx";
import Bars from "./Bars.jsx";
import Trend from "./Trend.jsx";
import { money, moneyFull, num, pct } from "../format.js";

function iso(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function presetRange(preset) {
  const today = new Date();
  if (preset === "month") {
    return { start_date: iso(new Date(today.getFullYear(), today.getMonth(), 1)), end_date: iso(today) };
  }
  if (preset === "quarter") {
    const q = Math.floor(today.getMonth() / 3) * 3;
    return { start_date: iso(new Date(today.getFullYear(), q, 1)), end_date: iso(today) };
  }
  return undefined; // "all"
}

// Generates and downloads a CSV export of current metrics
function exportMetricsCSV(metrics) {
  if (!metrics) return;
  const rows = [];
  rows.push(["Spend Analytics Executive Summary Export"]);
  rows.push(["Exported At", new Date().toLocaleString()]);
  rows.push([]);

  // Totals
  const t = metrics.totals || {};
  rows.push(["TOTALS"]);
  rows.push(["Total Spend", t.total_spend || 0]);
  rows.push(["Total Lines", t.lines || 0]);
  rows.push(["Suppliers Count", t.suppliers || 0]);
  rows.push(["Categories Count", t.categories || 0]);
  rows.push(["Maverick Spend", t.maverick_amount || 0]);
  rows.push([]);

  // By Category
  rows.push(["SPEND BY CATEGORY"]);
  rows.push(["Category", "Spend"]);
  (metrics.by_category || []).forEach((c) => rows.push([c.category, c.spend]));
  rows.push([]);

  // Top Suppliers
  rows.push(["TOP SUPPLIERS"]);
  rows.push(["Supplier Name", "Spend"]);
  (metrics.top_suppliers || []).forEach((s) => rows.push([s.supplier_name, s.spend]));
  rows.push([]);

  // Spend by BU
  rows.push(["SPEND BY BUSINESS UNIT"]);
  rows.push(["Business Unit", "Spend"]);
  (metrics.by_bu || []).forEach((b) => rows.push([b.bu_name, b.spend]));

  const csvContent = "data:text/csv;charset=utf-8," + rows.map((e) => e.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(",")).join("\n");
  const encodedUri = encodeURI(csvContent);
  const link = document.createElement("a");
  link.setAttribute("href", encodedUri);
  link.setAttribute("download", `Spend_Analytics_Summary_${iso(new Date())}.csv`);
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

// Executive Insights Callout Banner
function ExecutiveInsights({ metrics }) {
  const insights = useMemo(() => {
    if (!metrics) return [];
    const list = [];
    const t = metrics.totals || {};
    const total = Number(t.total_spend) || 0;
    const sup = metrics.top_suppliers || [];
    const leak = Number((metrics.overpayments || {}).total) || 0;

    if (total > 0 && sup.length) {
      const top5 = sup.slice(0, 5).reduce((a, r) => a + (Number(r.spend) || 0), 0);
      const ratio = top5 / total;
      if (ratio > 0.4) {
        list.push({
          type: "warning",
          icon: "⚠️",
          title: "High Supplier Concentration",
          text: `Top 5 suppliers represent ${pct(ratio)} (${money(top5)}) of total spend. Consider diversifying key vendor reliance.`,
        });
      }
    }

    if (t.maverick_amount && t.maverick_amount > 0) {
      list.push({
        type: "caution",
        icon: "🚨",
        title: "Maverick Spend Detected",
        text: `${money(t.maverick_amount)} (${pct(t.maverick_pct || 0)}) was purchased off-contract. Shifting this to preferred suppliers can capture instant savings.`,
      });
    }

    if (leak > 0) {
      list.push({
        type: "danger",
        icon: "💸",
        title: "Price Overpayment Leakage",
        text: `${money(leak)} paid above agreed contract rates. Review line item invoices to recover overbilled amounts.`,
      });
    }

    if (metrics.tail && metrics.tail.spend > 0) {
      list.push({
        type: "tip",
        icon: "💡",
        title: "Tail Spend Optimization",
        text: `Tail spend covers ${num(metrics.tail.supplier_count)} small suppliers (${money(metrics.tail.spend)}). Vendor consolidation could yield 5-10% cost reduction.`,
      });
    }

    return list;
  }, [metrics]);

  if (!insights.length) return null;

  return (
    <div className="insights-banner">
      <div className="insights-header">
        <div className="insights-title">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
          </svg>
          <span>AI Executive Spend Insights</span>
        </div>
        <span className="insights-badge">{insights.length} Actionable Observations</span>
      </div>

      <div className="insights-grid">
        {insights.map((item, idx) => (
          <div key={idx} className={`insight-card insight-${item.type}`}>
            <span className="insight-icon">{item.icon}</span>
            <div className="insight-body">
              <div className="insight-card-title">{item.title}</div>
              <p className="insight-card-text">{item.text}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function Dashboard({ metrics, error, onDrill, onRangeChange }) {
  const [preset, setPreset] = useState("all");
  const [customStart, setCustomStart] = useState("");
  const [customEnd, setCustomEnd] = useState("");
  const [dataLabelMode, setDataLabelMode] = useState("both"); // 'both' | 'val' | 'pct' | 'none'
  const [layoutMode, setLayoutMode] = useState("grid2"); // 'grid2' | 'compact' | 'focus'

  function applyPreset(p) {
    setPreset(p);
    if (p !== "custom") onRangeChange(presetRange(p));
  }

  function applyCustom() {
    if (!customStart || !customEnd) return;
    onRangeChange({ start_date: customStart, end_date: customEnd });
  }

  const range = metrics && metrics.range;
  const activeRange = range && (range.start_date || range.end_date);
  const rangeLabel = activeRange ? `${range.start_date || "…"} → ${range.end_date || "…"}` : "All-time dataset";

  return (
    <div className="dashboard-root">
      {/* Dashboard Top Control Bar */}
      <div className="dash-toolbar-container">
        <div className="dash-toolbar-row">
          <div className="dash-toolbar-group">
            <span className="toolbar-label">Time Horizon:</span>
            <div className="seg">
              <button type="button" className={preset === "all" ? "on" : ""} onClick={() => applyPreset("all")}>All time</button>
              <button type="button" className={preset === "month" ? "on" : ""} onClick={() => applyPreset("month")}>This month</button>
              <button type="button" className={preset === "quarter" ? "on" : ""} onClick={() => applyPreset("quarter")}>This quarter</button>
              <button type="button" className={preset === "custom" ? "on" : ""} onClick={() => applyPreset("custom")}>Custom</button>
            </div>
          </div>

          <div className="dash-toolbar-group">
            <span className="toolbar-label">Data Labels:</span>
            <select
              className="dash-control-select"
              value={dataLabelMode}
              onChange={(e) => setDataLabelMode(e.target.value)}
              aria-label="Data label mode"
            >
              <option value="both">Values & %</option>
              <option value="val">Values Only</option>
              <option value="pct">% Only</option>
              <option value="none">Labels Off</option>
            </select>
          </div>

          <div className="dash-toolbar-group">
            <span className="toolbar-label">Layout:</span>
            <div className="seg">
              <button
                type="button"
                className={layoutMode === "grid2" ? "on" : ""}
                onClick={() => setLayoutMode("grid2")}
                title="Standard 2-Column Grid"
              >
                Grid
              </button>
              <button
                type="button"
                className={layoutMode === "compact" ? "on" : ""}
                onClick={() => setLayoutMode("compact")}
                title="Compact View"
              >
                Compact
              </button>
              <button
                type="button"
                className={layoutMode === "focus" ? "on" : ""}
                onClick={() => setLayoutMode("focus")}
                title="Full-Width Focus Mode"
              >
                Focus
              </button>
            </div>
          </div>

          <div className="dash-toolbar-right">
            <button
              type="button"
              className="btn btn-ghost dash-export-btn"
              onClick={() => exportMetricsCSV(metrics)}
              disabled={!metrics}
              title="Export Current Spend Summary to CSV"
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="7 10 12 15 17 10" />
                <line x1="12" y1="15" x2="12" y2="3" />
              </svg>
              <span>Export CSV</span>
            </button>
          </div>
        </div>

        {preset === "custom" && (
          <div className="dash-custom-row">
            <input type="date" value={customStart} max={customEnd || undefined} onChange={(e) => setCustomStart(e.target.value)} />
            <span className="muted">to</span>
            <input type="date" value={customEnd} min={customStart || undefined} onChange={(e) => setCustomEnd(e.target.value)} />
            <button type="button" className="btn" onClick={applyCustom} disabled={!customStart || !customEnd}>
              Apply Filter
            </button>
          </div>
        )}

        <div className="dash-status-bar">
          <span className="dash-range-indicator">Showing: <b>{rangeLabel}</b></span>
        </div>
      </div>

      {error && <div className="dash-error" style={{ display: "block" }}>{error}</div>}

      {metrics && (
        <div className="dashboard-content-grid">
          {/* Executive AI Insights Banner */}
          <ExecutiveInsights metrics={metrics} />

          {/* KPI Cards Grid */}
          <div className="panel-section">
            <h3 className="section-head-title">Spend Overview KPIs</h3>
            <Kpis metrics={metrics} />
          </div>

          {/* Main Visualizations Grid */}
          <div className={`dash-grid-layout ${layoutMode}`}>
            <div className="panel chart-panel">
              <div className="panel-header">
                <h3>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
                  </svg>
                  <span>Spend by category</span>
                </h3>
              </div>
              <Bars
                rows={metrics.by_category || []}
                nameKey="category"
                valKey="spend"
                dim="category"
                onDrill={onDrill}
                dataLabelMode={dataLabelMode}
              />
            </div>

            <div className="panel chart-panel">
              <div className="panel-header">
                <h3>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
                    <circle cx="9" cy="7" r="4" />
                    <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
                    <path d="M16 3.13a4 4 0 0 1 0 7.75" />
                  </svg>
                  <span>Top suppliers</span>
                </h3>
              </div>
              <Bars
                rows={metrics.top_suppliers || []}
                nameKey="supplier_name"
                valKey="spend"
                dim="supplier"
                onDrill={onDrill}
                dataLabelMode={dataLabelMode}
              />
            </div>
          </div>

          {/* Full-width Trend Section */}
          <div className="panel chart-panel trend-panel-wrap">
            <div className="panel-header">
              <h3>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <polyline points="23 6 13.5 15.5 8.5 10.5 1 18" />
                  <polyline points="17 6 23 6 23 12" />
                </svg>
                <span>Monthly spend trend</span>
              </h3>
            </div>
            <Trend rows={metrics.monthly_trend || []} showDataLabels={dataLabelMode !== "none"} />
          </div>

          {/* Bottom Grid Visualizations */}
          <div className={`dash-grid-layout ${layoutMode}`}>
            <div className="panel chart-panel">
              <div className="panel-header">
                <h3>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <rect x="2" y="7" width="20" height="14" rx="2" ry="2" />
                    <path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16" />
                  </svg>
                  <span>Top items by spend</span>
                </h3>
              </div>
              <Bars
                rows={metrics.top_items || []}
                nameKey="item"
                valKey="spend"
                dataLabelMode={dataLabelMode}
              />
            </div>

            <div className="panel chart-panel">
              <div className="panel-header">
                <h3>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
                  </svg>
                  <span>Spend by business unit</span>
                </h3>
              </div>
              <Bars
                rows={metrics.by_bu || []}
                nameKey="bu_name"
                valKey="spend"
                dim="bu"
                onDrill={onDrill}
                dataLabelMode={dataLabelMode}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
