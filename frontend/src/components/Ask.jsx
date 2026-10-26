import React, { useEffect, useRef, useState } from "react";
import { jsPDF } from "jspdf";
import { apiAsk } from "../api.js";
import RowsTable from "./RowsTable.jsx";
import Sources from "./Sources.jsx";

const EXAMPLES = [
  "Top 5 categories by spend this year",
  "How much did we spend off-contract on IT hardware last quarter, by BU?",
  "Which suppliers did we overpay versus their contract price?",
  "Total maverick spend by category",
];

export default function Ask() {
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null); // { route, answer, sql, rows, sources, query }
  const [history, setHistory] = useState([]); // recent questions this session, most-recent first
  const inputRef = useRef(null);
  const timerRef = useRef(null);

  useEffect(() => () => clearInterval(timerRef.current), []);

  async function submit(e) {
    e.preventDefault();
    const question = q.trim();
    if (!question) return;
    setError("");
    setResult(null);
    setLoading(true);
    const t0 = Date.now();
    setElapsed(0);
    timerRef.current = setInterval(() => setElapsed(Math.round((Date.now() - t0) / 1000)), 1000);
    try {
      const data = await apiAsk(question);
      const entry = { ...data, query: question };
      setResult(entry);
      setHistory((h) => [{ id: Date.now(), question, data: entry }, ...h.filter((x) => x.question !== question)].slice(0, 8));
    } catch (err) {
      setError(err.message);
    } finally {
      clearInterval(timerRef.current);
      setLoading(false);
    }
  }

  function setExample(ex) {
    setQ(ex);
    if (inputRef.current) inputRef.current.focus();
  }

  function revisit(entry) {
    setError("");
    setQ(entry.question);
    setResult(entry.data);
  }

  const isDoc = result && result.route === "documents";
  const descriptive = result && result.route === "descriptive";
  const answerType = isDoc
    ? "\uD83D\uDCC4 Answer from documents + data"
    : descriptive
      ? "\uD83D\uDCAC Descriptive answer"
      : "\uD83D\uDCCA Data answer \u2014 grounded in SQL";
  const showSql = Boolean(result && !descriptive && result.sql);
  const rows = (result && result.rows) || [];

  function downloadPdfReport() {
    if (!result) return;
    const doc = new jsPDF({ unit: "pt", format: "a4" });
    const margin = 36;
    const pageW = doc.internal.pageSize.getWidth();
    const pageH = doc.internal.pageSize.getHeight();
    const contentW = pageW - margin * 2;
    const bottomPad = 42;
    const palette = {
      navy: [15, 23, 42],
      indigo: [67, 56, 202],
      slate: [71, 85, 105],
      soft: [247, 248, 252],
      border: [223, 228, 239],
      white: [255, 255, 255],
    };
    let y = 98;

    function drawHeader() {
      doc.setFillColor(...palette.navy);
      doc.rect(0, 0, pageW, 72, "F");
      doc.setFillColor(...palette.indigo);
      doc.rect(0, 72, pageW, 4, "F");
      doc.setTextColor(...palette.white);
      doc.setFont("helvetica", "bold");
      doc.setFontSize(17);
      doc.text("Spend Analytics Report", margin, 33);
      doc.setFont("helvetica", "normal");
      doc.setFontSize(10);
      doc.text("AI generated spend intelligence summary", margin, 51);
      doc.setDrawColor(...palette.border);
      doc.setLineWidth(1);
      doc.line(margin, 84, pageW - margin, 84);
      y = 98;
    }

    function ensureSpace(need) {
      if (y + need <= pageH - bottomPad) return;
      doc.addPage();
      drawHeader();
    }

    function drawTag(x, label) {
      doc.setFont("helvetica", "normal");
      doc.setFontSize(9);
      const w = Math.max(70, doc.getTextWidth(label) + 18);
      doc.setFillColor(238, 242, 255);
      doc.setDrawColor(208, 216, 255);
      doc.roundedRect(x, y - 11, w, 18, 8, 8, "FD");
      doc.setTextColor(67, 56, 202);
      doc.text(label, x + 9, y + 1);
      return w + 8;
    }

    function sectionTitle(title, subtitle = "") {
      ensureSpace(36);
      doc.setTextColor(...palette.indigo);
      doc.setFont("helvetica", "bold");
      doc.setFontSize(12);
      doc.text(title, margin, y);
      if (subtitle) {
        doc.setTextColor(...palette.slate);
        doc.setFont("helvetica", "normal");
        doc.setFontSize(9.5);
        doc.text(subtitle, margin, y + 13);
      }
      y += subtitle ? 22 : 16;
    }

    function writeCardText(text, options = {}) {
      const isCode = Boolean(options.code);
      const lineH = isCode ? 10.5 : 13;
      const fontSize = isCode ? 8.5 : 10.5;
      const fontName = isCode ? "courier" : "helvetica";
      const lines = doc.splitTextToSize(String(text || "(no content)"), contentW - 20);
      let idx = 0;

      while (idx < lines.length) {
        ensureSpace(44);
        const free = pageH - bottomPad - y;
        const maxLines = Math.max(3, Math.floor((free - 16) / lineH));
        const chunk = lines.slice(idx, idx + maxLines);
        const boxH = chunk.length * lineH + 14;

        doc.setFillColor(...(isCode ? [248, 250, 252] : palette.soft));
        doc.setDrawColor(...palette.border);
        doc.roundedRect(margin, y, contentW, boxH, 8, 8, "FD");

        doc.setTextColor(...(isCode ? [51, 65, 85] : [15, 23, 42]));
        doc.setFont(fontName, "normal");
        doc.setFontSize(fontSize);
        doc.text(chunk, margin + 10, y + 12);

        y += boxH + 10;
        idx += chunk.length;
      }
    }

    function drawRowsPreview() {
      if (!rows.length) return;
      const preview = rows.slice(0, 8);
      const cols = Object.keys(preview[0] || {}).slice(0, 5);
      if (!cols.length) return;

      const indexW = 26;
      const tableW = contentW - indexW;
      const colW = tableW / cols.length;
      const rowH = 19;

      const renderHeader = () => {
        ensureSpace(rowH + 8);
        doc.setFillColor(238, 242, 255);
        doc.setDrawColor(219, 226, 243);
        doc.roundedRect(margin, y, contentW, rowH, 6, 6, "FD");
        doc.setFont("helvetica", "bold");
        doc.setFontSize(8.5);
        doc.setTextColor(55, 65, 81);
        doc.text("#", margin + 8, y + 12);
        cols.forEach((c, i) => {
          const label = c.replace(/_/g, " ");
          doc.text(label.slice(0, 16), margin + indexW + i * colW + 4, y + 12);
        });
        y += rowH;
      };

      renderHeader();
      doc.setFont("helvetica", "normal");
      doc.setFontSize(8.5);
      doc.setTextColor(30, 41, 59);

      preview.forEach((r, rowIdx) => {
        ensureSpace(rowH + 2);
        if (y + rowH > pageH - bottomPad) {
          doc.addPage();
          drawHeader();
          sectionTitle("Data preview", "Continued");
          renderHeader();
        }
        if (rowIdx % 2 === 0) {
          doc.setFillColor(250, 251, 255);
          doc.rect(margin, y, contentW, rowH, "F");
        }
        doc.text(String(rowIdx + 1), margin + 8, y + 12);
        cols.forEach((c, i) => {
          const raw = r[c];
          const value = raw == null ? "-" : String(raw);
          const shortValue = value.length > 20 ? value.slice(0, 19) + "..." : value;
          doc.text(shortValue, margin + indexW + i * colW + 4, y + 12);
        });
        doc.setDrawColor(234, 238, 247);
        doc.line(margin, y + rowH, margin + contentW, y + rowH);
        y += rowH;
      });

      y += 8;
    }

    function drawSources() {
      const sources = (result.sources || []).slice(0, 12);
      if (!sources.length) return;
      sources.forEach((s, i) => {
        const heading = `${i + 1}. ${s.document || "Document"}${s.page ? ` (page ${s.page})` : ""}`;
        const snippet = s.text || s.excerpt || "Referenced source from retrieval layer.";
        sectionTitle(heading);
        writeCardText(snippet);
      });
    }

    drawHeader();

    const routeLabel = result.route || "sql";
    const generatedAt = new Date().toLocaleString();
    let x = margin;
    x += drawTag(x, `Generated: ${generatedAt}`);
    x += drawTag(x, `Route: ${routeLabel}`);
    drawTag(x, `Rows: ${rows.length}`);
    y += 22;

    sectionTitle("Question");
    writeCardText(result.query || "(no question)");

    sectionTitle("Answer");
    writeCardText(result.answer || "(no answer)");

    if (result.sql) {
      sectionTitle("Generated SQL", "The query used to ground this answer");
      writeCardText(result.sql, { code: true });
    }

    if (rows.length) {
      sectionTitle("Data preview", "Top rows returned by the query");
      drawRowsPreview();
    }

    drawSources();

    const totalPages = doc.getNumberOfPages();
    for (let p = 1; p <= totalPages; p += 1) {
      doc.setPage(p);
      doc.setDrawColor(...palette.border);
      doc.line(margin, pageH - 28, pageW - margin, pageH - 28);
      doc.setTextColor(100, 116, 139);
      doc.setFont("helvetica", "normal");
      doc.setFontSize(9);
      doc.text("Spend Analytics Agent", margin, pageH - 14);
      doc.text(`Page ${p} of ${totalPages}`, pageW - margin, pageH - 14, { align: "right" });
    }

    const stamp = new Date().toISOString().replace(/[T:]/g, "-").slice(0, 19);
    doc.save(`spend-report-${stamp}.pdf`);
  }

  return (
    <>
      <div className="card">
        <form className="ask-bar" onSubmit={submit}>
          <input
            type="text"
            ref={inputRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Ask about your spend — e.g. Top 5 categories by spend this year"
            autoComplete="off"
          />
          <button type="submit" className="btn" disabled={loading}>
            {loading ? <span className="spinner" /> : "Ask"}
          </button>
        </form>
        <div className="chips">
          {EXAMPLES.map((ex) => (
            <span className="chip" key={ex} onClick={() => setExample(ex)}>{ex}</span>
          ))}
        </div>
        {history.length > 0 && (
          <div className="ask-history">
            <div className="ask-history-head">
              <span>Recent questions</span>
              <button type="button" className="ask-history-clear" onClick={() => setHistory([])}>Clear</button>
            </div>
            <div className="chips">
              {history.map((h) => (
                <span
                  className="chip ask-history-chip"
                  key={h.id}
                  onClick={() => revisit(h)}
                  title="Revisit this answer"
                >
                  {h.question}
                </span>
              ))}
            </div>
          </div>
        )}
        {loading && (
          <div className="status" style={{ display: "block" }}>
            {"Thinking\u2026 " + elapsed + "s" +
              (elapsed > 8 ? " \u2014 the model may be warming up, this can take up to a minute." : "")}
          </div>
        )}
      </div>

      {error && <div className="error" style={{ display: "block" }}>{error}</div>}

      {result && (
        <div className="result card" style={{ display: "block" }}>
          <span className="answer-type" style={{ display: "inline-flex" }}>{answerType}</span>
          <div className="answer">{result.answer || "(no answer)"}</div>
          <div style={{ marginTop: 12 }}>
            <button type="button" className="btn btn-ghost" onClick={downloadPdfReport}>
              Download PDF report
            </button>
          </div>

          {showSql && (
            <details>
              <summary>Show generated SQL</summary>
              <pre>{result.sql || "(no SQL)"}</pre>
            </details>
          )}

          {showSql && rows.length > 0 && <RowsTable rows={rows} />}

          <Sources sources={result.sources || []} query={result.query} />
        </div>
      )}
    </>
  );
}
