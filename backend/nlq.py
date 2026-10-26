"""Natural-language querying: generate -> validate -> execute -> summarise.

All aggregation math happens in SQL. The SLM only translates the question into
SQL and explains the returned rows; it never computes totals itself.
"""
import re
from decimal import Decimal

import sqlglot
from sqlglot import exp

from config import settings
from db import run_select
from llm import chat
from rag import ALLOWED_VIEWS, retrieve_context  # noqa: F401 (re-export)

SQL_SYSTEM = (
    "You are a careful analytics engineer. Given a question and a set of allowed "
    "read-only PostgreSQL views, write ONE SELECT statement that answers it. "
    "Use ONLY the listed views and columns. Never write INSERT/UPDATE/DELETE/DDL. "
    "Return the SQL statement only - no explanation, no markdown fences."
)

SUMMARY_SYSTEM = (
    "You summarise SQL query results for a procurement analyst. Use ONLY the numbers "
    "in the provided rows - never invent figures. Answer in 1-3 concise sentences."
)


def _strip_sql(text: str) -> str:
    t = text.strip()
    # Defensively drop any <think>...</think> reasoning that leaked into the content.
    t = re.sub(r"<think>.*?</think>", "", t, flags=re.DOTALL | re.IGNORECASE).strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*", "", t).strip()
        t = re.sub(r"```$", "", t).strip()
    return t.rstrip(";").strip()


def _heuristic_sql(question: str) -> str | None:
    q = question.strip().lower()
    from rag import FEWSHOT
    for ex in FEWSHOT:
        if ex["q"].strip().lower() == q:
            return ex["sql"]

    if "top 5 categories" in q or ("top" in q and "categories" in q):
        return "SELECT category_level2 AS category, SUM(amount) AS total_spend FROM vw_spend GROUP BY category_level2 ORDER BY total_spend DESC LIMIT 5;"
    if "maverick" in q and "category" in q:
        return "SELECT category_level2 AS category, SUM(amount) AS maverick_spend FROM vw_spend WHERE is_maverick = true GROUP BY category_level2 ORDER BY maverick_spend DESC LIMIT 10;"
    if ("maverick" in q or "off-contract" in q or "off contract" in q) and ("bu" in q or "quarter" in q or "hardware" in q):
        return "SELECT bu_name, SUM(amount) AS off_contract_spend FROM vw_spend WHERE is_maverick = true GROUP BY bu_name ORDER BY off_contract_spend DESC LIMIT 10;"
    if "overpay" in q or "contract price" in q:
        return "SELECT supplier_name, SUM((unit_price - contracted_unit_price) * qty) AS overpayment FROM vw_spend WHERE contract_id IS NOT NULL AND unit_price > contracted_unit_price GROUP BY supplier_name ORDER BY overpayment DESC LIMIT 10;"
    if "top" in q and "supplier" in q:
        return "SELECT supplier_name, SUM(amount) AS total_spend FROM vw_spend GROUP BY supplier_name ORDER BY total_spend DESC LIMIT 10;"
    if "total spend" in q or "how much" in q:
        return "SELECT SUM(amount) AS total_spend FROM vw_spend;"
    return None


def generate_sql(question: str, context: str, error: str | None = None) -> str:
    try:
        user = f"{context}\n\nQuestion: {question}"
        if error:
            user += (
                f"\n\nYour previous attempt was invalid: {error}\n"
                "Return a corrected SQL statement."
            )
        raw = chat(
            [{"role": "system", "content": SQL_SYSTEM}, {"role": "user", "content": user}],
            temperature=0.0,
        )
        return _strip_sql(raw)
    except Exception as e:
        fallback = _heuristic_sql(question)
        if fallback:
            return fallback
        raise e



def validate_sql(sql: str) -> str:
    """Guardrail: exactly one read-only SELECT, allowlisted tables, enforced LIMIT."""
    statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    if len(statements) != 1:
        raise ValueError("Exactly one SQL statement is allowed.")
    tree = statements[0]
    if not isinstance(tree, exp.Select):
        raise ValueError("Only a single read-only SELECT is allowed.")

    cte_names = {cte.alias_or_name for cte in tree.find_all(exp.CTE)}
    allowed = {v.lower() for v in ALLOWED_VIEWS} | {n.lower() for n in cte_names}
    for tbl in tree.find_all(exp.Table):
        if tbl.name.lower() not in allowed:
            raise ValueError(f"Table not allowed: {tbl.name}")

    if not tree.args.get("limit"):
        tree = tree.limit(settings.row_limit)
    return tree.sql(dialect="duckdb")


def execute_sql(sql: str) -> list[dict]:
    return run_select(sql)


def _pretty(col: str) -> str:
    return col.replace("_", " ").strip().title()


def _is_number(v) -> bool:
    return isinstance(v, (int, float, Decimal)) and not isinstance(v, bool)


def _fmt(v) -> str:
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, Decimal):
        v = float(v)
    if isinstance(v, int):
        return f"{v:,}"
    if isinstance(v, float):
        return f"{v:,.2f}"
    return str(v)


def describe_rows(rows: list[dict]) -> str:
    """Deterministic, grounded one-liner built straight from the returned rows -
    no LLM call, so answers stay instant even when the SLM endpoint is slow."""
    if not rows:
        return "No matching rows were found."
    cols = list(rows[0].keys())
    if len(rows) == 1 and len(cols) == 1:
        return f"{_pretty(cols[0])}: {_fmt(rows[0][cols[0]])}."
    label_col = next((c for c in cols if not _is_number(rows[0][c])), cols[0])
    value_col = next((c for c in cols if _is_number(rows[0][c])), None)
    if value_col:
        top = rows[:5]
        listed = ", ".join(f"{r.get(label_col)} ({_fmt(r.get(value_col))})" for r in top)
        more = f", plus {len(rows) - 5} more" if len(rows) > 5 else ""
        return f"{len(rows)} result(s) by {_pretty(value_col)}: {listed}{more}."
    return f"{len(rows)} row(s) returned across: {', '.join(_pretty(c) for c in cols)}."


def summarise(question: str, rows: list[dict], sql: str) -> str:
    if not rows:
        return "No matching rows were found for that question."
    # Deterministic by default: skip the second (slow) SLM round-trip entirely.
    if not settings.summarise_with_llm:
        return describe_rows(rows)
    preview = rows[:50]
    user = (
        f"Question: {question}\n\nResult rows (JSON-like): {preview}\n\n"
        "Write a short, direct answer grounded only in these rows."
    )
    return chat(
        [
            {"role": "system", "content": SUMMARY_SYSTEM},
            {"role": "user", "content": user},
        ],
        temperature=0.0,
    )


# ---------------------------------------------------------------------------
# Question routing: data/table (SQL) vs. descriptive
# ---------------------------------------------------------------------------

ROUTER_SYSTEM = (
    "You route questions for a procurement spend-analytics assistant. Decide whether the "
    "question needs a DATABASE QUERY (it asks for specific numbers, totals, rankings, counts, "
    "lists, breakdowns or trends from the spend data) or is DESCRIPTIVE (a definition, "
    "explanation, interpretation, advice, or general/conceptual question that does not require "
    "querying data). Answer with ONLY one lowercase word: sql or descriptive."
)

DESCRIBE_SYSTEM = (
    "You are a procurement spend-analytics assistant. Answer the user's question clearly and "
    "concisely in 2-5 sentences. You may explain concepts (maverick / off-contract spend, tail "
    "spend, supplier consolidation, contract compliance, savings), give practical advice, or "
    "describe what this tool does. Do NOT invent specific figures; if the user needs actual "
    "numbers, suggest they ask a data question such as 'top categories by spend this year'."
)

_TOOL_CONTEXT = (
    "About this tool: it answers questions about procurement spend, grounded in read-only SQL "
    "over curated views. It covers suppliers, spend categories, business units, invoice dates, "
    "amounts, contracts and maverick (off-contract) spend, and shows a dashboard with totals, "
    "spend by category, top suppliers, monthly trend, supplier fragmentation and overpayments."
)

_DESCRIPTIVE_STARTS = (
    "what is", "what are", "what does", "what do", "explain", "define", "why", "how do i",
    "how can i", "how should", "tell me about", "describe", "can you explain",
)
_DESCRIPTIVE_HINTS = (
    "explain", "define", "definition", "recommend", "suggest", "best practice",
    "difference between", "meaning of", "help me understand",
)
_DATA_HINTS = (
    "how much", "how many", "total", "sum", "top ", "list ", "which ", "show me", "count",
    "average", "avg", "highest", "lowest", "most ", "least", "per ", " by ", "breakdown",
    "trend", "compare", "rank", "spend on", "spent",
)


def _heuristic_route(question: str) -> str:
    q = question.strip().lower()
    if any(h in q for h in _DATA_HINTS):
        return "sql"
    if q.startswith(_DESCRIPTIVE_STARTS) or any(h in q for h in _DESCRIPTIVE_HINTS):
        return "descriptive"
    return "sql"  # default to data (safer: numbers stay grounded in SQL)


DOC_SYSTEM = (
    "You are a procurement analyst. Answer the question using ONLY the provided document "
    "excerpts and data rows. Cite documents inline as [file, p.N]. Never invent figures. "
    "When comparing an agreed/contract price to what was actually paid, take the contract "
    "figure from the documents and the paid figure from the data rows, state the per-unit "
    "difference and the total. Answer in 2-5 sentences."
)

_DOC_HINTS = (
    "contract", "policy", "policies", "agreed price", "agreed rate", "agreed unit", "overpay",
    "overpaid", "overcharge", "overcharged", "clause", "terms", "approval limit",
    "per our contract", "as per contract", "contracted price", "should we have paid",
    "supposed to pay", "agreement", "sla", "correct price", "right price", "correct rate",
    "correct amount", "priced correctly", "pay too much", "paid too much", "within contract",
    "off contract", "off-contract", "price we agreed", "price agreed", "billed correctly",
)


def _documents_available() -> bool:
    try:
        import documents

        return documents.documents_available()
    except Exception:  # noqa: BLE001
        return False


def classify_question(question: str) -> str:
    """Route a question to SQL, a descriptive answer, or a document-grounded answer.

    Fast paths avoid the extra LLM call: contract/policy wording (when documents are
    loaded) -> 'documents'; explicit data phrasing -> 'sql'. Otherwise the LLM router
    decides, falling back to the heuristic if the SLM is unavailable.
    """
    q = question.strip().lower()
    if any(h in q for h in _DOC_HINTS) and _documents_available():
        return "documents"
    if any(h in q for h in _DATA_HINTS):
        return "sql"
    try:
        raw = chat(
            [{"role": "system", "content": ROUTER_SYSTEM},
             {"role": "user", "content": question}],
            temperature=0.0,
            max_tokens=8,
        ).strip().lower()
        if "descriptive" in raw:
            return "descriptive"
        if "sql" in raw:
            return "sql"
    except Exception:  # noqa: BLE001 - fall back to heuristic if the SLM is down
        pass
    return _heuristic_route(question)


def answer_with_documents(question: str, chunks: list[dict], rows: list[dict]) -> str:
    """Compose one answer that blends document excerpts with data rows, with citations."""
    if not chunks and not rows:
        return "I couldn't find anything in your documents or data to answer that."
    docs_text = "\n".join(
        f"[{c['doc_name']}, p.{c['page']}] {c['text']}" for c in chunks
    ) or "(no relevant documents)"
    rows_text = str(rows[:20]) if rows else "(no data rows)"
    user = f"Question: {question}\n\nDocument excerpts:\n{docs_text}\n\nData rows: {rows_text}"
    try:
        return chat(
            [{"role": "system", "content": DOC_SYSTEM}, {"role": "user", "content": user}],
            temperature=0.1,
            max_tokens=400,
        )
    except Exception:  # noqa: BLE001
        if rows:
            return describe_rows(rows)
        return "The document assistant isn't reachable right now."


def describe(question: str) -> str:
    """Answer a descriptive / conceptual question (no database query)."""
    try:
        return chat(
            [{"role": "system", "content": DESCRIBE_SYSTEM},
             {"role": "user", "content": f"{_TOOL_CONTEXT}\n\nQuestion: {question}"}],
            temperature=0.2,
        )
    except Exception:  # noqa: BLE001
        return (
            "I can explain spend-analytics concepts and how this tool works, but the language "
            "model isn't reachable right now. For data questions try, for example, "
            "\u201ctop categories by spend this year\u201d."
        )
