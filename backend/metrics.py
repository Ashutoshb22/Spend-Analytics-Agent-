"""Deterministic dashboard metrics computed with read-only SQL over vw_spend.

Optionally scoped to an invoice-date range (inclusive). Dates are validated as
``YYYY-MM-DD`` and passed as bound parameters, so the filter stays injection-safe.
"""
import re

from db import run_select

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _date_filter(start_date: str | None, end_date: str | None) -> tuple[str, list]:
    """Return an SQL predicate (over invoice_date) plus its bound params."""
    conds: list[str] = []
    params: list = []
    if start_date:
        if not _DATE_RE.match(start_date):
            raise ValueError("start_date must be in YYYY-MM-DD format")
        conds.append("invoice_date >= ?")
        params.append(start_date)
    if end_date:
        if not _DATE_RE.match(end_date):
            raise ValueError("end_date must be in YYYY-MM-DD format")
        conds.append("invoice_date <= ?")
        params.append(end_date)
    return " AND ".join(conds), params


def compute_metrics(start_date: str | None = None, end_date: str | None = None) -> dict:
    cond, dparams = _date_filter(start_date, end_date)
    where = f"WHERE {cond} " if cond else ""
    and_ = f"AND {cond} " if cond else ""

    totals = run_select(
        "SELECT COALESCE(SUM(amount), 0) AS total_spend, COUNT(*) AS lines, "
        "COUNT(DISTINCT supplier_name) AS suppliers, COUNT(DISTINCT category_level2) AS categories "
        f"FROM vw_spend {where}",
        list(dparams),
    )[0]

    by_category = run_select(
        "SELECT category_level2 AS category, SUM(amount) AS spend "
        f"FROM vw_spend {where}GROUP BY 1 ORDER BY spend DESC",
        list(dparams),
    )

    top_suppliers = run_select(
        "SELECT supplier_name, SUM(amount) AS spend "
        f"FROM vw_spend {where}GROUP BY 1 ORDER BY spend DESC LIMIT 10",
        list(dparams),
    )

    mav = run_select(
        "SELECT COALESCE(SUM(amount) FILTER (WHERE is_maverick), 0) AS maverick, "
        f"COALESCE(SUM(amount), 0) AS total FROM vw_spend {where}",
        list(dparams),
    )[0]
    total = float(mav["total"]) or 0.0
    maverick_amount = float(mav["maverick"])
    maverick_pct = (maverick_amount / total) if total else 0.0

    monthly_trend = run_select(
        "SELECT CAST(date_trunc('month', invoice_date) AS DATE) AS month, SUM(amount) AS spend "
        f"FROM vw_spend WHERE invoice_date IS NOT NULL {and_}GROUP BY 1 ORDER BY 1",
        list(dparams),
    )

    overpay_rows = run_select(
        "SELECT supplier_name, SUM((unit_price - contracted_unit_price) * qty) AS overpayment "
        "FROM vw_spend WHERE contract_id IS NOT NULL AND contracted_unit_price IS NOT NULL "
        f"AND unit_price > contracted_unit_price {and_}GROUP BY 1 ORDER BY overpayment DESC LIMIT 10",
        list(dparams),
    )
    overpay_total = run_select(
        "SELECT COALESCE(SUM((unit_price - contracted_unit_price) * qty), 0) AS total "
        "FROM vw_spend WHERE contract_id IS NOT NULL AND contracted_unit_price IS NOT NULL "
        f"AND unit_price > contracted_unit_price {and_}",
        list(dparams),
    )[0]["total"]

    pareto = run_select(
        f"WITH s AS (SELECT supplier_name, SUM(amount) AS spend FROM vw_spend {where}GROUP BY 1), "
        "r AS (SELECT supplier_name, spend, SUM(spend) OVER (ORDER BY spend DESC) AS running, "
        "SUM(spend) OVER () AS tot FROM s) "
        "SELECT supplier_name, spend, running / NULLIF(tot, 0) AS cumulative "
        "FROM r ORDER BY spend DESC",
        list(dparams),
    )
    tail = [p for p in pareto if (p["cumulative"] or 0) > 0.8]
    tail_spend = sum(float(p["spend"]) for p in tail)

    fragmentation = run_select(
        "SELECT category_level2 AS category, COUNT(DISTINCT supplier_name) AS suppliers, "
        f"SUM(amount) AS spend FROM vw_spend {where}GROUP BY 1 ORDER BY suppliers DESC, spend DESC",
        list(dparams),
    )

    top_items = run_select(
        "SELECT item, COUNT(*) AS transactions, COALESCE(SUM(qty), 0) AS qty, SUM(amount) AS spend "
        f"FROM vw_spend WHERE item IS NOT NULL {and_}GROUP BY 1 ORDER BY spend DESC LIMIT 10",
        list(dparams),
    )

    by_bu = run_select(
        "SELECT bu_name, SUM(amount) AS spend FROM vw_spend "
        f"WHERE bu_name IS NOT NULL {and_}GROUP BY 1 ORDER BY spend DESC LIMIT 10",
        list(dparams),
    )

    return {
        "range": {"start_date": start_date, "end_date": end_date},
        "totals": {
            "total_spend": totals["total_spend"],
            "lines": totals["lines"],
            "suppliers": totals["suppliers"],
            "categories": totals["categories"],
            "maverick_amount": maverick_amount,
            "maverick_pct": maverick_pct,
        },
        "by_category": by_category,
        "top_suppliers": top_suppliers,
        "monthly_trend": monthly_trend,
        "overpayments": {"rows": overpay_rows, "total": overpay_total},
        "pareto": pareto,
        "tail": {"supplier_count": len(tail), "spend": tail_spend},
        "fragmentation": fragmentation,
        "top_items": top_items,
        "by_bu": by_bu,
    }
