// Number / text formatting helpers (ported from the original vanilla app, unchanged).

export function money(v) {
  if (v === null || v === undefined) return "\u2014";
  const n = Number(v), abs = Math.abs(n);
  if (abs >= 1e6) return "$" + (n / 1e6).toFixed(2) + "M";
  if (abs >= 1e3) return "$" + (n / 1e3).toFixed(1) + "K";
  return "$" + n.toFixed(0);
}

export function moneyFull(v) {
  if (v === null || v === undefined) return "\u2014";
  return "$" + Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 });
}

export function num(v) {
  return v === null || v === undefined ? "\u2014" : Number(v).toLocaleString();
}

export function pct(v) {
  return (Number(v) * 100).toFixed(1) + "%";
}

export function fmt(v) {
  if (v === null || v === undefined) return "";
  if (typeof v === "number") return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
  return String(v);
}

export function isNum(v) {
  return typeof v === "number";
}

export function escapeHtml(t) {
  return String(t).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
}

const SRC_STOP = new Set(
  ("the a an of for to and or in on is are was were we did do does our you "
    + "your that this with at by from as it be an on").split(" ")
);

export function cleanSnippet(text) {
  return String(text || "")
    .replace(/[-_=*.\u2013\u2014]{3,}/g, " ") // drop ASCII rules / separators
    .replace(/\s+/g, " ") // collapse whitespace
    .replace(/^[^A-Za-z0-9\u20ac\u00a3$\u20b9]+/, "") // trim leading noise
    .trim();
}

export function highlightTerms(escaped, query) {
  const toks = (query || "").toLowerCase().match(/[a-z]{3,}/g) || [];
  const stems = [...new Set(toks
    .filter((t) => !SRC_STOP.has(t))
    .map((t) => (t.length > 3 && t.endsWith("s") ? t.slice(0, -1) : t)))];
  if (!stems.length) return escaped;
  const pat = stems.map((s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "s?").join("|");
  return escaped.replace(new RegExp("\\b(" + pat + ")\\b", "gi"), "<mark>$1</mark>");
}
