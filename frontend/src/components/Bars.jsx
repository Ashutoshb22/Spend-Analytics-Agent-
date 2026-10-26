import React, { useState, useMemo } from "react";
import { money, moneyFull, pct } from "../format.js";
import DonutChart from "./DonutChart.jsx";

const GRADIENTS = [
  "linear-gradient(90deg, #6366f1, #4f46e5)", // Indigo
  "linear-gradient(90deg, #10b981, #059669)", // Emerald
  "linear-gradient(90deg, #8b5cf6, #7c3aed)", // Purple
  "linear-gradient(90deg, #f59e0b, #d97706)", // Amber
  "linear-gradient(90deg, #ec4899, #db2777)", // Pink
  "linear-gradient(90deg, #06b6d4, #0891b2)", // Cyan
  "linear-gradient(90deg, #f97316, #ea580c)", // Orange
  "linear-gradient(90deg, #3b82f6, #2563eb)", // Blue
  "linear-gradient(90deg, #84cc16, #65a30d)", // Lime
  "linear-gradient(90deg, #a855f7, #9333ea)", // Violet
];

export default function Bars({
  rows,
  nameKey,
  valKey,
  dim,
  onDrill,
  title,
  showControls = true,
  dataLabelMode = "both", // 'both' | 'val' | 'pct' | 'none'
}) {
  const [viewMode, setViewMode] = useState("bars"); // 'bars' | 'donut' | 'table'
  const [topN, setTopN] = useState(10);
  const [search, setSearch] = useState("");
  const [labelMode, setLabelMode] = useState(dataLabelMode);

  // Sync labelMode when parent prop changes
  React.useEffect(() => {
    setLabelMode(dataLabelMode);
  }, [dataLabelMode]);

  const filteredRows = useMemo(() => {
    if (!rows || !rows.length) return [];
    let list = rows;
    if (search.trim()) {
      const q = search.toLowerCase().trim();
      list = list.filter((r) => String(r[nameKey] ?? "").toLowerCase().includes(q));
    }
    return list;
  }, [rows, nameKey, search]);

  const displayRows = useMemo(() => {
    if (topN === 0) return filteredRows;
    return filteredRows.slice(0, topN);
  }, [filteredRows, topN]);

  const grandTotal = useMemo(() => {
    if (!rows || !rows.length) return 0;
    return rows.reduce((sum, r) => sum + (Number(r[valKey]) || 0), 0);
  }, [rows, valKey]);

  if (!rows || !rows.length) return <div className="muted-center">No data available</div>;

  const max = Math.max(...displayRows.map((r) => Number(r[valKey]) || 0), 1);

  return (
    <div className="chart-card-wrap">
      {showControls && (
        <div className="chart-controls-bar">
          <div className="chart-controls-left">
            <div className="chart-view-switch" role="group" aria-label="View mode">
              <button
                type="button"
                className={`chart-view-btn${viewMode === "bars" ? " active" : ""}`}
                onClick={() => setViewMode("bars")}
                title="Bar Chart View"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <line x1="12" y1="20" x2="12" y2="10" />
                  <line x1="18" y1="20" x2="18" y2="4" />
                  <line x1="6" y1="20" x2="6" y2="16" />
                </svg>
                <span>Bars</span>
              </button>
              <button
                type="button"
                className={`chart-view-btn${viewMode === "donut" ? " active" : ""}`}
                onClick={() => setViewMode("donut")}
                title="Donut Chart View"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M21.21 15.89A10 10 0 1 1 8 2.83" />
                  <path d="M22 12A10 10 0 0 0 12 2v10z" />
                </svg>
                <span>Donut</span>
              </button>
              <button
                type="button"
                className={`chart-view-btn${viewMode === "table" ? " active" : ""}`}
                onClick={() => setViewMode("table")}
                title="Table View"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M3 3h18v18H3z" />
                  <path d="M3 9h18" />
                  <path d="M3 15h18" />
                  <path d="M9 3v18" />
                </svg>
                <span>Table</span>
              </button>
            </div>

            <div className="chart-search-wrap">
              <input
                type="text"
                placeholder="Filter items..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="chart-search-input"
              />
              {search && (
                <button type="button" className="chart-search-clear" onClick={() => setSearch("")}>
                  ×
                </button>
              )}
            </div>
          </div>

          <div className="chart-controls-right">
            <select
              className="chart-top-select"
              value={topN}
              onChange={(e) => setTopN(Number(e.target.value))}
              aria-label="Top N filter"
            >
              <option value={5}>Top 5</option>
              <option value={10}>Top 10</option>
              <option value={0}>All ({rows.length})</option>
            </select>
          </div>
        </div>
      )}

      {displayRows.length === 0 ? (
        <div className="muted-center">No matching rows found</div>
      ) : viewMode === "donut" ? (
        <DonutChart
          rows={displayRows}
          nameKey={nameKey}
          valKey={valKey}
          dim={dim}
          onDrill={onDrill}
          showLabels={labelMode !== "none"}
        />
      ) : viewMode === "table" ? (
        <div className="chart-table-wrap">
          <table className="chart-data-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Name</th>
                <th className="num">Spend</th>
                <th className="num">% Share</th>
                <th style={{ width: "100px" }}>Distribution</th>
              </tr>
            </thead>
            <tbody>
              {displayRows.map((r, i) => {
                const val = Number(r[valKey]) || 0;
                const share = grandTotal > 0 ? val / grandTotal : 0;
                const name = String(r[nameKey] ?? "—");
                const clickable = Boolean(dim);
                return (
                  <tr
                    key={i}
                    className={clickable ? "clickable-tr" : ""}
                    onClick={() => clickable && onDrill && onDrill(dim, name)}
                  >
                    <td className="row-num">{i + 1}</td>
                    <td className="row-name">{name}</td>
                    <td className="num font-mono">{moneyFull(val)}</td>
                    <td className="num font-mono">{pct(share)}</td>
                    <td>
                      <div className="mini-track">
                        <div
                          className="mini-fill"
                          style={{
                            width: `${Math.min(100, Math.max(4, share * 100))}%`,
                            background: GRADIENTS[i % GRADIENTS.length],
                          }}
                        />
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        /* Default 'bars' view */
        <div className="bars-list">
          {displayRows.map((r, i) => {
            const value = Number(r[valKey]) || 0;
            const width = Math.max(2, (value / max) * 100);
            const share = grandTotal > 0 ? value / grandTotal : 0;
            const name = String(r[nameKey] ?? "—");
            const clickable = Boolean(dim);
            const gradient = GRADIENTS[i % GRADIENTS.length];
            const open = () => clickable && onDrill && onDrill(dim, name);

            // Construct Data Label based on labelMode
            let dataLabelText = "";
            if (labelMode === "both") {
              dataLabelText = `${money(value)} (${pct(share)})`;
            } else if (labelMode === "val") {
              dataLabelText = money(value);
            } else if (labelMode === "pct") {
              dataLabelText = pct(share);
            }

            return (
              <div
                key={i}
                className={clickable ? "bar-row clickable" : "bar-row"}
                role={clickable ? "button" : undefined}
                tabIndex={clickable ? 0 : undefined}
                title={`${name}: ${moneyFull(r[valKey])} (${pct(share)})${
                  clickable ? " — click to drill down" : ""
                }`}
                onClick={clickable ? open : undefined}
                onKeyDown={
                  clickable
                    ? (e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          open();
                        }
                      }
                    : undefined
                }
              >
                <div className="bar-name-col">
                  <span className="bar-rank-badge">{i + 1}</span>
                  <span className="name" title={name}>
                    {name}
                  </span>
                </div>
                <div className="bar-track-wrap">
                  <div className="bar-track">
                    <div className="bar-fill" style={{ width: width + "%", background: gradient }}>
                      {/* Integrated data label inside bar if wide enough */}
                      {width > 28 && labelMode !== "none" && (
                        <span className="bar-label-inside">{dataLabelText}</span>
                      )}
                    </div>
                  </div>
                </div>
                <div className="bar-val-col">
                  <span className="val">{money(value)}</span>
                  {labelMode !== "none" && <span className="val-pct-badge">{pct(share)}</span>}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
