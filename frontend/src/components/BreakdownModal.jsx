import React, { useEffect, useState } from "react";
import { apiBreakdown, apiLines } from "../api.js";
import { money, moneyFull } from "../format.js";

// Drill-down modal with two levels:
//   1. the items behind a clicked category / supplier / business unit
//   2. click an item -> the individual invoice lines behind it
// Controlled by `drill` ({ dim, value }); null means closed.
export default function BreakdownModal({ drill, onClose }) {
  const [state, setState] = useState({ loading: false, error: "", data: null });
  const [item, setItem] = useState(null); // selected item => level 2
  const [lines, setLines] = useState({ loading: false, error: "", data: null });

  // Level 1: load the item breakdown when the modal opens.
  useEffect(() => {
    if (!drill) return undefined;
    setItem(null);
    let cancelled = false;
    setState({ loading: true, error: "", data: null });
    apiBreakdown(drill.dim, drill.value)
      .then((data) => { if (!cancelled) setState({ loading: false, error: "", data }); })
      .catch((e) => { if (!cancelled) setState({ loading: false, error: e.message, data: null }); });
    return () => { cancelled = true; };
  }, [drill]);

  // Level 2: load the invoice lines when an item is selected.
  useEffect(() => {
    if (!drill || !item) return undefined;
    let cancelled = false;
    setLines({ loading: true, error: "", data: null });
    apiLines(drill.dim, drill.value, item)
      .then((data) => { if (!cancelled) setLines({ loading: false, error: "", data }); })
      .catch((e) => { if (!cancelled) setLines({ loading: false, error: e.message, data: null }); });
    return () => { cancelled = true; };
  }, [drill, item]);

  // Escape: from the invoice view go back to the item list; from the item list close.
  useEffect(() => {
    if (!drill) return undefined;
    const onKey = (e) => { if (e.key === "Escape") { if (item) setItem(null); else onClose(); } };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [drill, item, onClose]);

  if (!drill) return null;

  const sub = drill.dim === "supplier"
    ? "Items purchased from this supplier"
    : drill.dim === "bu"
      ? "Items bought by this business unit"
      : "Items bought in this category";
  const items = (state.data && state.data.items) || [];

  return (
    <div
      className="modal-overlay open"
      onClick={(e) => { if (e.target.classList.contains("modal-overlay")) onClose(); }}
    >
      <div className="modal">
        {item ? (
          <InvoiceLines item={item} value={drill.value} lines={lines} onBack={() => setItem(null)} onClose={onClose} />
        ) : (
          <>
            <div className="modal-head">
              <div>
                <div className="modal-title">{drill.value}</div>
                <div className="muted">{sub}</div>
              </div>
              <button type="button" className="modal-close" aria-label="Close" onClick={onClose}>✕</button>
            </div>

            <div className="muted" style={{ margin: "6px 0 10px", fontWeight: 600, color: "var(--text)" }}>
              {state.data ? money(state.data.total) + " total · " + state.data.lines + " transaction" + (state.data.lines === 1 ? "" : "s") : ""}
            </div>

            <div>
              {state.loading && <div className="muted-center">Loading…</div>}
              {state.error && <div className="dash-error" style={{ display: "block" }}>{state.error}</div>}
              {state.data && items.length === 0 && <div className="muted-center">No line items found</div>}
              {state.data && items.length > 0 && (
                <table className="bd-table">
                  <thead>
                    <tr>
                      <th>Item</th>
                      <th className="num">Qty</th>
                      <th className="num" title="Number of separate purchase records (invoice / PO line items) for this item">Transactions</th>
                      <th className="num">Spend</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((it, i) => {
                      const qty = Number(it.qty) || 0;
                      const name = String(it.item ?? "\u2014");
                      return (
                        <tr key={i} className="bd-click" onClick={() => setItem(name)} title="Click to see the invoices">
                          <td>{name} <span className="bd-chevron">›</span></td>
                          <td className="num">{qty ? qty.toLocaleString() : "\u2014"}</td>
                          <td className="num">{it.lines}</td>
                          <td className="num">{moneyFull(it.spend)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function InvoiceLines({ item, value, lines, onBack, onClose }) {
  const rows = (lines.data && lines.data.rows) || [];
  const fmtDate = (d) => (d ? String(d).slice(0, 10) : "\u2014");
  return (
    <>
      <div className="modal-head">
        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <button type="button" className="modal-close" aria-label="Back" onClick={onBack}>←</button>
          <div>
            <div className="modal-title">{item}</div>
            <div className="muted">Invoices · at {value}</div>
          </div>
        </div>
        <button type="button" className="modal-close" aria-label="Close" onClick={onClose}>✕</button>
      </div>

      <div className="muted" style={{ margin: "6px 0 10px", fontWeight: 600, color: "var(--text)" }}>
        {lines.data ? money(lines.data.total) + " total · " + lines.data.lines + " invoice" + (lines.data.lines === 1 ? "" : "s") : ""}
      </div>

      <div>
        {lines.loading && <div className="muted-center">Loading…</div>}
        {lines.error && <div className="dash-error" style={{ display: "block" }}>{lines.error}</div>}
        {lines.data && rows.length === 0 && <div className="muted-center">No invoice lines found</div>}
        {lines.data && rows.length > 0 && (
          <table className="bd-table">
            <thead>
              <tr>
                <th>Invoice date</th>
                <th className="num">Qty</th>
                <th className="num">Unit price</th>
                <th className="num">Amount</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  <td>{fmtDate(r.invoice_date)}</td>
                  <td className="num">{r.qty == null ? "\u2014" : Number(r.qty).toLocaleString()}</td>
                  <td className="num">{r.unit_price == null ? "\u2014" : moneyFull(r.unit_price)}</td>
                  <td className="num">{moneyFull(r.amount)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}

