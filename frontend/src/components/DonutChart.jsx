import React, { useState } from "react";
import { money, moneyFull, pct } from "../format.js";

const PALETTE = [
  "#4f46e5", // Indigo
  "#10b981", // Emerald
  "#8b5cf6", // Purple
  "#f59e0b", // Amber
  "#ec4899", // Pink
  "#06b6d4", // Cyan
  "#f97316", // Orange
  "#3b82f6", // Blue
  "#84cc16", // Lime
  "#a855f7", // Violet
];

function polarToCartesian(cx, cy, r, angleInDegrees) {
  const angleInRadians = ((angleInDegrees - 90) * Math.PI) / 180.0;
  return {
    x: cx + r * Math.cos(angleInRadians),
    y: cy + r * Math.sin(angleInRadians),
  };
}

function describeArc(x, y, rOuter, rInner, startAngle, endAngle) {
  const sweep = endAngle - startAngle;
  const effectiveEnd = sweep >= 360 ? startAngle + 359.999 : endAngle;

  const startOuter = polarToCartesian(x, y, rOuter, effectiveEnd);
  const endOuter = polarToCartesian(x, y, rOuter, startAngle);
  const startInner = polarToCartesian(x, y, rInner, effectiveEnd);
  const endInner = polarToCartesian(x, y, rInner, startAngle);

  const largeArcFlag = sweep <= 180 ? "0" : "1";

  return [
    "M", startOuter.x, startOuter.y,
    "A", rOuter, rOuter, 0, largeArcFlag, 0, endOuter.x, endOuter.y,
    "L", endInner.x, endInner.y,
    "A", rInner, rInner, 0, largeArcFlag, 1, startInner.x, startInner.y,
    "Z",
  ].join(" ");
}

export default function DonutChart({ rows, nameKey, valKey, dim, onDrill, showLabels = true }) {
  const [hoverIndex, setHoverIndex] = useState(null);

  if (!rows || !rows.length) {
    return <div className="muted-center">No data available</div>;
  }

  const items = rows.slice(0, 10).map((r) => ({
    name: String(r[nameKey] ?? "Unknown"),
    value: Number(r[valKey]) || 0,
    raw: r,
  }));

  const total = items.reduce((sum, item) => sum + item.value, 0);

  if (total <= 0) {
    return <div className="muted-center">No non-zero spend data</div>;
  }

  const CX = 120, CY = 120, R_OUTER = 95, R_INNER = 58;

  let currentAngle = 0;
  const slices = items.map((item, idx) => {
    const fraction = item.value / total;
    const angleSpan = fraction * 360;
    const startAngle = currentAngle;
    const endAngle = currentAngle + angleSpan;
    const midAngle = startAngle + angleSpan / 2;
    currentAngle = endAngle;

    const pathD = describeArc(CX, CY, R_OUTER, R_INNER, startAngle, endAngle);
    const color = PALETTE[idx % PALETTE.length];

    const labelPos = polarToCartesian(CX, CY, (R_OUTER + R_INNER) / 2, midAngle);

    return {
      ...item,
      fraction,
      startAngle,
      endAngle,
      midAngle,
      pathD,
      color,
      labelPos,
    };
  });

  const activeSlice = hoverIndex !== null ? slices[hoverIndex] : null;

  return (
    <div className="donut-container">
      <div className="donut-graphic-wrap">
        <svg viewBox="0 0 240 240" className="donut-svg" role="img" aria-label="Donut Chart">
          {slices.map((slice, i) => {
            const isHovered = hoverIndex === i;
            const clickable = Boolean(dim);
            return (
              <g key={i} className="donut-slice-group">
                <path
                  d={slice.pathD}
                  fill={slice.color}
                  className={`donut-slice${isHovered ? " active" : ""}${clickable ? " clickable" : ""}`}
                  onMouseEnter={() => setHoverIndex(i)}
                  onMouseLeave={() => setHoverIndex(null)}
                  onClick={() => clickable && onDrill && onDrill(dim, slice.name)}
                  style={{
                    transform: isHovered ? "scale(1.04)" : "scale(1)",
                    transformOrigin: `${CX}px ${CY}px`,
                    transition: "transform 0.18s ease, opacity 0.18s ease",
                    opacity: hoverIndex !== null && !isHovered ? 0.65 : 1,
                    cursor: clickable ? "pointer" : "default",
                  }}
                />
                {showLabels && slice.fraction >= 0.06 && (
                  <text
                    x={slice.labelPos.x}
                    y={slice.labelPos.y}
                    className="donut-slice-label"
                    textAnchor="middle"
                    dominantBaseline="central"
                  >
                    {pct(slice.fraction)}
                  </text>
                )}
              </g>
            );
          })}
          <circle cx={CX} cy={CY} r={R_INNER - 2} fill="var(--surface)" />
          <text x={CX} y={CY - 10} className="donut-center-title" textAnchor="middle">
            {activeSlice ? activeSlice.name : "Total"}
          </text>
          <text x={CX} y={CY + 10} className="donut-center-value" textAnchor="middle">
            {activeSlice ? money(activeSlice.value) : money(total)}
          </text>
          {activeSlice && (
            <text x={CX} y={CY + 26} className="donut-center-sub" textAnchor="middle">
              {pct(activeSlice.fraction)} of total
            </text>
          )}
        </svg>
      </div>

      <div className="donut-legend">
        {slices.map((slice, i) => {
          const clickable = Boolean(dim);
          const isHovered = hoverIndex === i;
          return (
            <div
              key={i}
              className={`donut-legend-item${isHovered ? " active" : ""}${clickable ? " clickable" : ""}`}
              onMouseEnter={() => setHoverIndex(i)}
              onMouseLeave={() => setHoverIndex(null)}
              onClick={() => clickable && onDrill && onDrill(dim, slice.name)}
              title={`${slice.name}: ${moneyFull(slice.value)} (${pct(slice.fraction)})`}
            >
              <span className="donut-swatch" style={{ background: slice.color }} />
              <span className="donut-legend-name">{slice.name}</span>
              <span className="donut-legend-val">{money(slice.value)}</span>
              {showLabels && <span className="donut-legend-pct">{pct(slice.fraction)}</span>}
            </div>
          );
        })}
      </div>
    </div>
  );
}
