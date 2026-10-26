import React from "react";
import { escapeHtml, cleanSnippet, highlightTerms } from "../format.js";

// Cited document excerpts for a document-grounded answer. The snippet is HTML-
// escaped first, then query terms are wrapped in <mark>, so injecting it via
// dangerouslySetInnerHTML is safe.
export default function Sources({ sources, query }) {
  if (!sources || !sources.length) return null;
  const docNames = [...new Set(sources.map((s) => s.doc_name))];
  const sub =
    sources.length + " excerpt" + (sources.length === 1 ? "" : "s") +
    " from " + (docNames.length === 1 ? docNames[0] : docNames.length + " documents");

  return (
    <div style={{ marginTop: "18px" }}>
      <div className="src-head-row">
        <span className="src-title">Sources</span>
        <span className="src-sub">{sub}</span>
      </div>
      <div>
        {sources.map((s, i) => {
          const clean = cleanSnippet(s.text);
          const snippet = clean.length > 300 ? clean.slice(0, 300).replace(/\s+\S*$/, "") + "\u2026" : clean;
          const html = highlightTerms(escapeHtml(snippet), query);
          return (
            <div className="source" key={i}>
              <div className="src-head">
                <span className="src-file">{"\uD83D\uDCC4 "}{s.doc_name}</span>
                <span className="src-page">page {s.page}</span>
                {i === 0 && sources.length > 1 && <span className="src-best">Best match</span>}
              </div>
              <div className="src-text" dangerouslySetInnerHTML={{ __html: html }} />
            </div>
          );
        })}
      </div>
    </div>
  );
}
