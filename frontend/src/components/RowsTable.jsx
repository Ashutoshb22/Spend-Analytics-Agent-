import React from "react";
import { fmt, isNum } from "../format.js";

// Generic results table for the "Ask" data answers.
export default function RowsTable({ rows }) {
  if (!rows || rows.length === 0) {
    return <div className="muted" style={{ marginTop: "14px" }}>No rows returned.</div>;
  }
  const cols = Object.keys(rows[0]);
  return (
    <div id="rowsWrap">
      <div className="muted" style={{ marginTop: "14px" }}>
        {rows.length + " row" + (rows.length === 1 ? "" : "s")}
      </div>
      <div style={{ overflowX: "auto" }}>
        <table>
          <tbody>
            <tr>{cols.map((c) => <th key={c}>{c}</th>)}</tr>
            {rows.map((row, i) => (
              <tr key={i}>
                {cols.map((c) => (
                  <td key={c} className={isNum(row[c]) ? "num" : undefined}>{fmt(row[c])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
