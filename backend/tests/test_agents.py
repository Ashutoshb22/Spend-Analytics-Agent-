"""Tests for Phase 3 Multi-Agent Orchestration & Proactive Intelligence (agents.py)."""

import pytest
import agents


def test_ingestion_data_quality_agent(monkeypatch):
    fake_rows = [{"total_rows": 100, "unmapped_categories": 5, "unitemised_rows": 10, "missing_suppliers": 0}]
    monkeypatch.setattr(agents.tools, "execute_sql_query", lambda sql: {"success": True, "rows": fake_rows})

    agent = agents.IngestionDataQualityAgent()
    res = agent.run_data_quality_audit()

    assert res["agent"] == "IngestionDataQualityAgent"
    assert res["total_records"] == 100
    assert res["unmapped_categories"] == 5
    assert res["data_quality_score"] < 100.0


def test_procurement_compliance_agent(monkeypatch):
    fake_doc_res = {"success": True, "results": [{"doc_name": "DHL_SLA.pdf", "text": "Net 30"}]}
    fake_db_res = {"success": True, "rows": [{"supplier_name": "DHL", "total_spend": 10000.0, "maverick_spend": 2500.0, "active_contracts": 1}]}

    monkeypatch.setattr(agents.tools, "search_contract_documents", lambda q, top_k=3: fake_doc_res)
    monkeypatch.setattr(agents.tools, "execute_sql_query", lambda sql: fake_db_res)

    agent = agents.ProcurementComplianceAgent()
    res = agent.verify_vendor_compliance("DHL")

    assert res["vendor_name"] == "DHL"
    assert res["total_spend"] == 10000.0
    assert res["maverick_percentage"] == 25.0
    assert res["compliance_status"] == "NON_COMPLIANT"


def test_savings_negotiation_agent(monkeypatch):
    fake_opps = {
        "success": True,
        "opportunities": [
            {"title": "Consolidate IT Software", "category": "IT Software", "supplier": "Vendor A", "target_annual": 15000.0},
        ],
    }
    monkeypatch.setattr(agents.tools, "detect_savings_opportunities", lambda kind=None: fake_opps)

    agent = agents.SavingsNegotiationAgent()
    res = agent.generate_negotiation_playbook()

    assert res["opportunity_count"] == 1
    assert res["total_target_savings"] == 15000.0
    assert len(res["negotiation_strategies"]) == 1


def test_supervisor_agent(monkeypatch):
    monkeypatch.setattr(agents.IngestionDataQualityAgent, "run_data_quality_audit", lambda self: {
        "data_quality_score": 95.0,
        "total_records": 50,
    })
    monkeypatch.setattr(agents.ProcurementComplianceAgent, "verify_vendor_compliance", lambda self, v: {
        "vendor_name": v,
        "compliance_status": "COMPLIANT",
    })
    monkeypatch.setattr(agents.SavingsNegotiationAgent, "generate_negotiation_playbook", lambda self: {
        "total_target_savings": 20000.0,
        "opportunity_count": 2,
    })

    supervisor = agents.SupervisorAgent()
    res = supervisor.process_multi_agent_request("Audit DHL vendor contracts", vendor="DHL")

    assert "DHL" in res["question"]
    assert "Multi-Agent Audit Completed" in res["executive_summary"]
    assert len(res["sub_agent_results"]) == 3


def test_run_proactive_spend_audit(monkeypatch):
    fake_mav = {"success": True, "rows": [{"category": "IT Software", "maverick_amount": 12000.0, "transaction_count": 4}]}
    fake_frag = {"success": True, "rows": [{"category": "Office Supplies", "supplier_count": 4, "total_spend": 25000.0}]}

    def mock_execute_sql(sql):
        if "is_maverick = true" in sql:
            return fake_mav
        return fake_frag

    monkeypatch.setattr(agents.tools, "execute_sql_query", mock_execute_sql)

    res = agents.run_proactive_spend_audit()
    assert res["audit_status"] == "COMPLETED"
    assert res["total_findings"] == 2
    severities = {f["severity"] for f in res["findings"]}
    assert "HIGH" in severities
    assert "MEDIUM" in severities
