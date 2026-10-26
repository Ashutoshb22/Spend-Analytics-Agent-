"""Tests for the deterministic answer summary (no SLM required).

Run:  python -m pytest -q tests/test_summarise.py
"""
from decimal import Decimal

from nlq import describe_rows


def test_empty_rows():
    assert describe_rows([]) == "No matching rows were found."


def test_scalar_result():
    assert describe_rows([{"total_spend": 4293689.53}]) == "Total Spend: 4,293,689.53."


def test_ranked_results():
    out = describe_rows(
        [
            {"category": "Freight & Logistics", "spend": 827335.0},
            {"category": "IT Software", "spend": 726500.0},
        ]
    )
    assert out.startswith("2 result(s) by Spend:")
    assert "Freight & Logistics (827,335.00)" in out


def test_truncates_long_lists():
    rows = [{"supplier_name": f"S{i}", "spend": float(100 - i)} for i in range(8)]
    out = describe_rows(rows)
    assert "plus 3 more" in out


def test_handles_decimal_values():
    # DuckDB returns SUM(amount) as a Decimal; it must still be treated as numeric.
    out = describe_rows([{"category": "IT Software", "spend": Decimal("726500.00")}])
    assert out.startswith("1 result(s) by Spend:")
    assert "IT Software (726,500.00)" in out
