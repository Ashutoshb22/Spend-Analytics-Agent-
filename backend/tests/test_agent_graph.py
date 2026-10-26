"""Tests for Phase 2 Agentic State Graph (graph.py)."""

import pytest
import graph
import tools


def test_data_question_executes_agentic_flow(monkeypatch):
    monkeypatch.setattr(tools, "execute_sql_query", lambda sql: {
        "success": True,
        "sql": "SELECT category_level2, SUM(amount) FROM vw_spend GROUP BY category_level2;",
        "rows": [["IT Software", 50000], ["Office Supplies", 12000]],
    })
    monkeypatch.setattr(graph, "summarise", lambda q, rows, sql: "The top category is IT Software with $50,000.")

    res = graph.answer_question("Top categories by spend")
    assert res["question"] == "Top categories by spend"
    assert "IT Software" in res["answer"]
    assert len(res["rows"]) == 2
    assert len(res["steps"]) >= 1
    assert res["steps"][0]["step"] == "query_spend_database"


def test_descriptive_question_routes_directly():
    res = graph.answer_question("What is maverick spend?")
    assert res["question"] == "What is maverick spend?"
    assert res["route"] == "descriptive"
    assert len(res["answer"]) > 0


def test_documents_question_executes_document_search(monkeypatch):
    fake_docs = [{"doc_name": "SLA_Vendor.pdf", "page": 1, "text": "Net 30 payment terms."}]
    monkeypatch.setattr(tools, "search_contract_documents", lambda q, top_k=4: {
        "success": True,
        "results": fake_docs,
    })

    res = graph.answer_question("What are the payment terms in SLA_Vendor.pdf?")
    assert res["route"] == "documents"
    assert len(res["sources"]) == 1
    assert res["sources"][0]["doc_name"] == "SLA_Vendor.pdf"


def test_reflection_repair_loop(monkeypatch):
    calls = []

    def mock_generate_sql(q, context, error=None):
        calls.append(error)
        if error is None:
            return "INVALID SQL QUERY"
        return "SELECT SUM(amount) FROM vw_spend;"

    def mock_validate_sql(sql):
        if sql == "INVALID SQL QUERY":
            raise ValueError("Syntax error in SQL near INVALID")
        return sql

    monkeypatch.setattr(graph, "generate_sql", mock_generate_sql)
    monkeypatch.setattr(graph, "validate_sql", mock_validate_sql)
    monkeypatch.setattr(tools, "execute_sql_query", lambda sql: {
        "success": True,
        "sql": sql,
        "rows": [{"total": 9999}],
    })

    res = graph.answer_question("How much did we spend total?")
    assert len(calls) >= 2  # Proves reflection & retry repair node was triggered
    assert calls[0] is None  # Initial attempt
    assert "Syntax error" in str(calls[1])  # Repair attempt received prior error!
