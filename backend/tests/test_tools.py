"""Tests for Phase 1 Agent Tools (tools.py)."""

import pytest
import tools


def test_tools_registry_contains_expected_tools():
    expected_tools = {
        "query_spend_database",
        "search_contract_documents",
        "detect_savings_opportunities",
        "get_database_schema",
        "classify_spend_item",
        "compute_spend_metrics",
    }
    assert expected_tools.issubset(set(tools.TOOLS_REGISTRY.keys()))


def test_get_openai_tools_specs():
    specs = tools.get_openai_tools_specs()
    assert len(specs) == len(tools.TOOLS_REGISTRY)
    names = {s["function"]["name"] for s in specs}
    assert "query_spend_database" in names
    assert "search_contract_documents" in names
    
    # Check JSON Schema structure of query_spend_database
    sql_spec = next(s for s in specs if s["function"]["name"] == "query_spend_database")
    assert sql_spec["type"] == "function"
    assert "parameters" in sql_spec["function"]
    assert "sql" in sql_spec["function"]["parameters"]["properties"]


def test_execute_sql_query_tool_valid(monkeypatch):
    monkeypatch.setattr(tools.nlq, "validate_sql", lambda sql: sql)
    monkeypatch.setattr(tools.nlq, "execute_sql", lambda sql: [{"total": 1000}])
    
    res = tools.execute_sql_query("SELECT SUM(amount) FROM vw_spend;")
    assert res["success"] is True
    assert res["row_count"] == 1
    assert res["rows"] == [{"total": 1000}]


def test_execute_sql_query_tool_invalid():
    # Attempting forbidden write operation
    res = tools.execute_sql_query("DELETE FROM spend;")
    assert res["success"] is False
    assert "error" in res
    assert res["row_count"] == 0


def test_search_contract_documents_tool(monkeypatch):
    fake_hits = [{"filename": "contract.pdf", "page": 1, "text": "Volume discount 5%"}]
    monkeypatch.setattr(tools.documents, "search", lambda q, k: fake_hits)

    res = tools.search_contract_documents("volume discount", top_k=2)
    assert res["success"] is True
    assert res["count"] == 1
    assert res["results"] == fake_hits


def test_detect_savings_opportunities_tool(monkeypatch):
    fake_opps = [
        {"id": 1, "kind": "consolidation", "target_annual": 5000},
        {"id": 2, "kind": "price_variance", "target_annual": 2000},
    ]
    monkeypatch.setattr(tools.savings, "detect_opportunities", lambda: fake_opps)

    # All opportunities
    res_all = tools.detect_savings_opportunities()
    assert res_all["success"] is True
    assert res_all["opportunity_count"] == 2

    # Filtered by kind
    res_filtered = tools.detect_savings_opportunities(kind="consolidation")
    assert res_filtered["success"] is True
    assert res_filtered["opportunity_count"] == 1
    assert res_filtered["opportunities"][0]["kind"] == "consolidation"


def test_get_database_schema_tool():
    res = tools.get_database_schema("top categories")
    assert res["success"] is True
    assert "vw_spend" in res["allowed_views"]
    assert "vw_spend" in res["context"]


def test_compute_spend_metrics_tool(monkeypatch):
    monkeypatch.setattr(tools.metrics, "compute_metrics", lambda: {"total_spend": 50000})

    res = tools.compute_spend_metrics("ytd")
    assert res["success"] is True
    assert res["metrics"]["total_spend"] == 50000


def test_execute_tool_by_name():
    # Valid tool invocation via router
    res = tools.execute_tool_by_name("get_database_schema", {"question": "test"})
    assert res["success"] is True

    # Unknown tool
    res_unknown = tools.execute_tool_by_name("non_existent_tool", {})
    assert res_unknown["success"] is False
    assert "not registered" in res_unknown["error"]

    # Invalid arguments
    res_bad_arg = tools.execute_tool_by_name("query_spend_database", {})
    assert res_bad_arg["success"] is False
    assert "error" in res_bad_arg
