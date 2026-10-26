"""AI data-classification agent.

On every upload this agent runs FIRST: it perceives the file (headers + a small
sample of rows), reasons about it with the org SLM to decide *what kind of data*
was uploaded, and returns a decision the API uses to route the pipeline
(analyse as spend vs. classify-only). If the SLM is unavailable or errors, it
falls back to a deterministic keyword classifier, so it always returns an answer.

Public API:
    classify_upload(content, filename, use_llm=True) -> dict
        {category, confidence, rationale, method, is_spend, columns, row_count, needs_ocr}
"""
from __future__ import annotations

import json
import re

from config import settings
from ingest import _canon, detect_header_row, map_columns, read_tabular

# The categories the agent may assign.
CATEGORIES = [
    "Procurement Spend Ledger",
    "Invoices",
    "Receipts / Expenses",
    "Purchase Orders",
    "Supplier / Vendor Master",
    "Contracts",
    "General Ledger",
    "Budget / Forecast",
    "Other / Non-spend",
]

# Image / document types we can recognise but not yet parse (need OCR).
_IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".tif", ".tiff", ".heic", ".pdf")

# Keyword signatures for the deterministic fallback classifier.
_SIGNATURES: dict[str, list[str]] = {
    "Procurement Spend Ledger": ["supplier", "vendor", "amount", "spend", "category",
                                  "cost center", "business unit", "po", "maverick"],
    "Invoices": ["invoice", "invoice number", "invoice date", "amount due", "bill to",
                 "tax", "due date", "remit"],
    "Receipts / Expenses": ["receipt", "merchant", "total", "tax", "payment", "card",
                            "expense", "employee", "reimburse"],
    "Purchase Orders": ["po number", "purchase order", "order date", "quantity",
                        "unit price", "delivery", "requisition"],
    "Supplier / Vendor Master": ["supplier", "vendor", "address", "country", "tax id",
                                 "contact", "email", "payment terms", "bank", "duns"],
    "Contracts": ["contract", "contract id", "start date", "end date", "term",
                  "renewal", "counterparty", "value", "effective"],
    "General Ledger": ["account", "gl", "debit", "credit", "journal", "posting",
                       "period", "ledger"],
    "Budget / Forecast": ["budget", "forecast", "plan", "actual", "variance", "fiscal",
                          "period", "target"],
}

_CLASSIFY_SYSTEM = (
    "You are a data-classification agent for a procurement spend-analytics platform. "
    "Given the column headers and a few sample rows of an uploaded file, classify it into "
    "exactly ONE of these categories:\n" + ", ".join(CATEGORIES) + ".\n"
    "Respond with STRICT JSON only (no markdown, no prose) in the form: "
    '{"category": "<one of the categories>", "confidence": <number 0..1>, '
    '"rationale": "<one short sentence>"}.'
)


# ---------------------------------------------------------------------------
# Perception: profile the file
# ---------------------------------------------------------------------------

def profile_upload(content: bytes, filename: str) -> dict:
    """Return column headers + a few sample rows for classification."""
    rows = [r for r in read_tabular(content, filename) if any(str(c).strip() for c in r)]
    if not rows:
        return {"columns": [], "sample_rows": [], "row_count": 0}
    hdr_i = detect_header_row(rows)
    header = [str(c).strip() for c in rows[hdr_i]]
    data = rows[hdr_i + 1:]
    return {"columns": header, "sample_rows": data[:5], "row_count": len(data)}


def _looks_analyzable(columns: list[str]) -> bool:
    """True if the existing spend pipeline could actually load this file
    (needs a supplier-like column and an amount- or unit-price-like column)."""
    m = map_columns([str(c) for c in columns])
    return "supplier_name" in m and ("amount" in m or "unit_price" in m)


# ---------------------------------------------------------------------------
# Reasoning: LLM classifier (+ deterministic fallback)
# ---------------------------------------------------------------------------

def _parse_json(text: str) -> dict | None:
    t = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip().strip("`")
    m = re.search(r"\{.*\}", t, flags=re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _match_category(s: str) -> str:
    s2 = s.strip().lower()
    for c in CATEGORIES:
        if c.lower() == s2:
            return c
    for c in CATEGORIES:
        if c.lower() in s2 or s2 in c.lower():
            return c
    if "invoice" in s2:
        return "Invoices"
    if "receipt" in s2 or "expense" in s2:
        return "Receipts / Expenses"
    if "supplier" in s2 or "vendor" in s2:
        return "Supplier / Vendor Master"
    if "contract" in s2:
        return "Contracts"
    if "ledger" in s2 or s2 == "gl":
        return "General Ledger"
    if "purchase order" in s2 or "po" == s2:
        return "Purchase Orders"
    return "Other / Non-spend"


def _llm_classify(profile: dict) -> dict:
    user = (
        f"Column headers: {profile['columns']}\n"
        f"Sample rows: {profile['sample_rows']}\n"
        "Classify this uploaded file."
    )
    raw = _chat_classify(user)
    data = _parse_json(raw)
    if not data or "category" not in data:
        raise ValueError("classifier did not return usable JSON")
    try:
        conf = float(data.get("confidence"))
    except (TypeError, ValueError):
        conf = 0.7
    return {
        "category": _match_category(str(data.get("category", ""))),
        "confidence": max(0.0, min(1.0, conf)),
        "rationale": str(data.get("rationale", "")).strip()[:300],
        "method": f"AI agent ({settings.slm_model})",
    }


def _chat_classify(user: str) -> str:
    # Imported lazily so importing this module never requires the SLM.
    from llm import chat

    return chat(
        [{"role": "system", "content": _CLASSIFY_SYSTEM}, {"role": "user", "content": user}],
        temperature=0.0,
        max_tokens=200,
    )


def _heuristic_classify(profile: dict) -> dict:
    blob = " ".join(_canon(c) for c in profile["columns"])
    best, best_hits, best_score = "Other / Non-spend", [], 0
    for cat, sigs in _SIGNATURES.items():
        hits = [s for s in sigs if s in blob]
        if len(hits) > best_score:
            best, best_hits, best_score = cat, hits, len(hits)
    if best_score == 0:
        return {
            "category": "Other / Non-spend",
            "confidence": 0.3,
            "rationale": "The columns don't match known procurement or finance patterns.",
            "method": "heuristic",
        }
    return {
        "category": best,
        "confidence": round(min(0.55 + 0.1 * best_score, 0.9), 2),
        "rationale": f"Columns match {best} signals: {', '.join(best_hits[:5])}.",
        "method": "heuristic",
    }


# ---------------------------------------------------------------------------
# The agent entry point
# ---------------------------------------------------------------------------

def classify_upload(content: bytes, filename: str, use_llm: bool = True) -> dict:
    """Classify what kind of data an uploaded file contains."""
    name = (filename or "").lower()
    if name.endswith(_IMAGE_EXT):
        return {
            "category": "Receipt / Document (image)",
            "confidence": 0.6,
            "rationale": "The upload is an image or PDF (e.g. a scanned receipt or invoice); "
                         "extracting line items requires OCR.",
            "method": "file-type",
            "is_spend": False,
            "columns": [],
            "row_count": 0,
            "needs_ocr": True,
        }

    try:
        profile = profile_upload(content, filename)
    except Exception:  # noqa: BLE001 - unreadable file
        profile = {"columns": [], "sample_rows": [], "row_count": 0}

    if not profile["columns"]:
        return {
            "category": "Empty / Unreadable",
            "confidence": 0.0,
            "rationale": "No tabular data could be read from the file.",
            "method": "heuristic",
            "is_spend": False,
            "columns": [],
            "row_count": 0,
            "needs_ocr": False,
        }

    result = None
    if use_llm and settings.slm_base_url and settings.slm_api_key:
        try:
            result = _llm_classify(profile)
        except Exception:  # noqa: BLE001 - fall back to deterministic
            result = None
    if result is None:
        result = _heuristic_classify(profile)

    result["is_spend"] = _looks_analyzable(profile["columns"])
    result["columns"] = profile["columns"]
    result["row_count"] = profile["row_count"]
    result["needs_ocr"] = False
    return result
