import React, { useMemo, useRef, useState } from "react";
import { money, moneyFull, pct } from "../format.js";

const W = 800, H = 210, PAD_X = 40, PAD_Y = 32;

// Smooth cubic Bezier spline calculator for natural SVG curves
function buildSmoothPath(points) {
  if (!points || points.length === 0) return { line: "", area: "" };
  if (points.length === 1) {
    const p = points[0];
    return {
      line: `M ${p.x},${p.y} L ${p.x},${p.y}`,
      area: `M ${p.x},${H - PAD_Y} L ${p.x},${p.y} L ${p.x},${H - PAD_Y} Z`,
    };
  }

  // Smooth control points
  let line = `M ${points[0].x.toFixed(1)},${points[0].y.toFixed(1)}`;
  for (let i = 0; i < points.length - 1; i++) {
    const p0 = points[i];
    const p1 = points[i + 1];
    const cpX = (p0.x + p1.x) / 2;
    line += ` C ${cpX.toFixed(1)},${p0.y.toFixed(1)} ${cpX.toFixed(1)},${p1.y.toFixed(1)} ${p1.x.toFixed(1)},${p1.y.toFixed(1)}`;
  }

  const first = points[0];
  const last = points[points.length - 1];
  const area = `${line} L ${last.x.toFixed(1)},${(H - PAD_Y).toFixed(1)} L ${first.x.toFixed(1)},${(H - PAD_Y).toFixed(1)} Z`;

  return { line, area };
}

export default function Trend({ rows, showDataLabels = true }) {
  const svgRef = useRef(null);
  const [tip, setTip] = useState(null);
  const [showBaseline, setShowBaseline] = useState(true);

  const model = useMemo(() => {
    if (!rows || !rows.length) return null;
    const vals = rows.map((r) => Number(r.spend) || 0);
    const max = Math.max(...vals, 1);
    const min = Math.min(...vals, 0);
    const sum = vals.reduce((a, b) => a + b, 0);
    const avg = sum / (vals.length || 1);

    const xOf = (i) =>
      PAD_X + (rows.length === 1 ? (W - 2 * PAD_X) / 2 : (i / (rows.length - 1)) * (W - 2 * PAD_X));
    const yOf = (v) => H - PAD_Y - ((v - min) / (max - min || 1)) * (H - 2 * PAD_Y);

    const pts = rows.map((r, i) => {
      const prevVal = i > 0 ? vals[i - 1] : null;
      const momPct = prevVal && prevVal > 0 ? (vals[i] - prevVal) / prevVal : null;
      return {
        x: xOf(i),
        y: yOf(vals[i]),
        month: r.month,
        val: vals[i],
        momPct,
        idx: i,
      };
    });

    const peakPt = pts.reduce((maxPt, p) => (p.val > maxPt.val ? p : maxPt), pts[0]);
    const minPt = pts.reduce((minPt, p) => (p.val < minPt.val ? p : minPt), pts[0]);
    const latestPt = pts[pts.length - 1];

    const { line, area } = buildSmoothPath(pts);
    const avgY = yOf(avg);

    // MoM for latest period vs previous
    const latestMom = pts.length > 1 ? pts[pts.length - 1].momPct : null;

    return { max, min, sum, avg, pts, line, area, avgY, peakPt, minPt, latestPt, latestMom };
  }, [rows]);

  if (!model) return <div className="muted-center">No dated rows available</div>;

  const { max, sum, avg, pts, line, area, avgY, peakPt, minPt, latestPt, latestMom } = model;
  const f0 = PAD_X / W,
    f1 = (W - PAD_X) / W;

  function showHover(clientX) {
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    let frac = (clientX - rect.left) / rect.width;
    frac = Math.max(f0, Math.min(f1, frac));
    const t = rows.length === 1 ? 0 : (frac - f0) / (f1 - f0);
    const p = pts[Math.round(t * (rows.length - 1))];
    setTip({ ...p, rectW: rect.width, rectH: rect.height });
  }

  return (
    <div className="trend-component">
      <div className="trend-header-row">
        <div className="trend-stats-summary">
          <div className="trend-stat-chip">
            <span className="lbl">Total Period Spend</span>
            <span className="val">{money(sum)}</span>
          </div>
          <div className="trend-stat-chip">
            <span className="lbl">Monthly Average</span>
            <span className="val">{money(avg)}</span>
          </div>
          <div className="trend-stat-chip highlight-peak">
            <span className="lbl">Peak ({peakPt.month})</span>
            <span className="val">{money(peakPt.val)}</span>
          </div>
          {latestMom !== null && (
            <div className={`trend-stat-chip ${latestMom > 0 ? "trend-up" : "trend-down"}`}>
              <span className="lbl">Latest MoM Trend</span>
              <span className="val">
                {latestMom > 0 ? "▲ +" : "▼ "}
                {pct(Math.abs(latestMom))}
              </span>
            </div>
          )}
        </div>

        <div className="trend-toolbar-actions">
          <button
            type="button"
            className={`btn-pill-toggle${showBaseline ? " active" : ""}`}
            onClick={() => setShowBaseline((v) => !v)}
          >
            Average Baseline
          </button>
        </div>
      </div>

      <div className="trend-wrap">
        <svg
          ref={svgRef}
          viewBox={`0 0 ${W} ${H}`}
          width="100%"
          role="img"
          aria-label="Monthly spend trend line chart with data labels"
          onMouseMove={(e) => showHover(e.clientX)}
          onMouseLeave={() => setTip(null)}
          onTouchMove={(e) => {
            if (e.touches[0]) showHover(e.touches[0].clientX);
          }}
        >
          <defs>
            <linearGradient id="trendAreaGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#4f46e5" stopOpacity="0.28" />
              <stop offset="60%" stopColor="#6366f1" stopOpacity="0.08" />
              <stop offset="100%" stopColor="#818cf8" stopOpacity="0.0" />
            </linearGradient>

            <filter id="shadowGlow" x="-20%" y="-20%" width="140%" height="140%">
              <feDropShadow dx="0" dy="4" stdDeviation="4" floodColor="#4f46e5" floodOpacity="0.25" />
            </filter>
          </defs>

          {/* Grid lines */}
          <line x1={PAD_X} y1={PAD_Y} x2={W - PAD_X} y2={PAD_Y} className="trend-grid-line" />
          <line x1={PAD_X} y1={(H - PAD_Y + PAD_Y) / 2} x2={W - PAD_X} y2={(H - PAD_Y + PAD_Y) / 2} className="trend-grid-line" />
          <line x1={PAD_X} y1={H - PAD_Y} x2={W - PAD_X} y2={H - PAD_Y} className="trend-grid-line" />

          {/* Average baseline overlay */}
          {showBaseline && (
            <g className="trend-baseline-group">
              <line
                x1={PAD_X}
                y1={avgY}
                x2={W - PAD_X}
                y2={avgY}
                stroke="#6366f1"
                strokeWidth="1.5"
                strokeDasharray="4 4"
                opacity="0.65"
              />
              <text x={W - PAD_X + 4} y={avgY + 4} fill="#6366f1" fontSize="10" fontWeight="600">
                Avg ({money(avg)})
              </text>
            </g>
          )}

          {/* Filled Area */}
          <path d={area} fill="url(#trendAreaGradient)" />

          {/* Curved Trend Line */}
          <path d={line} fill="none" stroke="#4f46e5" strokeWidth="3" strokeLinecap="round" filter="url(#shadowGlow)" />

          {/* Active Hover Crosshair Line */}
          {tip && (
            <line
              x1={tip.x}
              y1={PAD_Y}
              x2={tip.x}
              y2={H - PAD_Y}
              stroke="#94a3b8"
              strokeWidth="1"
              strokeDasharray="3 3"
            />
          )}

          {/* Data Nodes & Labels */}
          {pts.map((p, i) => {
            const isPeak = p === peakPt;
            const isLatest = p === latestPt;
            const isHovered = tip && tip.idx === p.idx;

            return (
              <g key={i} className="trend-node-group">
                {/* Outer Glow Ring on hover */}
                {isHovered && <circle cx={p.x} cy={p.y} r="8" fill="#818cf8" opacity="0.3" />}

                {/* Node Circle */}
                <circle
                  cx={p.x}
                  cy={p.y}
                  r={isPeak || isLatest || isHovered ? "5" : "3.5"}
                  fill={isPeak ? "#10b981" : "#4f46e5"}
                  stroke="#ffffff"
                  strokeWidth="2"
                  className="trend-pt-node"
                />

                {/* Explicit Data Label above node */}
                {showDataLabels && (
                  <g className="trend-node-label-group">
                    <rect
                      x={p.x - 22}
                      y={p.y - 24}
                      width="44"
                      height="16"
                      rx="4"
                      fill={isPeak ? "#059669" : "#1e293b"}
                      opacity="0.88"
                    />
                    <text
                      x={p.x}
                      y={p.y - 13}
                      fill="#ffffff"
                      fontSize="9.5"
                      fontWeight="600"
                      textAnchor="middle"
                    >
                      {money(p.val)}
                    </text>
                  </g>
                )}
              </g>
            );
          })}
        </svg>

        {/* Hover Floating Glass Tooltip */}
        {tip && (
          <div
            className="trend-tip-box"
            style={{
              left: `${(tip.x / W) * tip.rectW}px`,
              top: `${(tip.y / H) * tip.rectH}px`,
            }}
          >
            <div className="tip-month">{tip.month}</div>
            <div className="tip-val">{moneyFull(tip.val)}</div>
            {tip.momPct !== null && (
              <div className={`tip-mom ${tip.momPct >= 0 ? "up" : "down"}`}>
                {tip.momPct >= 0 ? "▲ +" : "▼ "}
                {pct(Math.abs(tip.momPct))} vs prev month
              </div>
            )}
          </div>
        )}
      </div>

      <div className="trend-footer-legend">
        <span>{rows[0]?.month}</span>
        <span className="legend-mid">
          Peak: <b>{peakPt.month} ({money(peakPt.val)})</b>
        </span>
        <span>{rows[rows.length - 1]?.month}</span>
      </div>
    </div>
  );
}
