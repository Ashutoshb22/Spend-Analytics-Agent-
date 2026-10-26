"""Guardrail tests for validate_sql (no database or SLM required).

Run:  python -m pytest -q tests/test_validate_sql.py
"""
import pytest

from nlq import validate_sql


def test_injects_limit():
    assert "LIMIT" in validate_sql("SELECT amount FROM vw_spend").upper()


def test_rejects_non_select():
    with pytest.raises(ValueError):
        validate_sql("DROP TABLE vw_spend")


def test_rejects_disallowed_table():
    with pytest.raises(ValueError):
        validate_sql("SELECT * FROM pg_user")


def test_rejects_multiple_statements():
    with pytest.raises(ValueError):
        validate_sql("SELECT 1 FROM vw_spend; DROP TABLE vw_spend")


def test_allows_cte_over_allowed_view():
    out = validate_sql(
        "WITH t AS (SELECT supplier_name, SUM(amount) s FROM vw_spend GROUP BY supplier_name) "
        "SELECT * FROM t ORDER BY s DESC"
    )
    assert "vw_spend" in out.lower()
