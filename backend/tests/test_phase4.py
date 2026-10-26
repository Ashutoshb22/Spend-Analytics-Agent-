"""Tests for Phase 4 Human-in-the-Loop & Memory Engine (approval.py & memory.py)."""

import pytest
import approval
import memory


def test_create_and_list_pending_approvals():
    payload = {"title": "Consolidate AWS", "target_annual": 10000.0}
    app_info = approval.create_pending_approval(
        action_type="create_savings_opportunity",
        title="Consolidate AWS Spend",
        details="Consolidate uncoordinated accounts",
        payload=payload,
    )

    assert app_info["status"] == "pending"
    assert app_info["action_type"] == "create_savings_opportunity"

    pending_list = approval.list_pending_approvals(status_filter="pending")
    assert len(pending_list) >= 1
    found = next((item for item in pending_list if item["id"] == app_info["id"]), None)
    assert found is not None
    assert found["title"] == "Consolidate AWS Spend"


def test_review_approval_decision(monkeypatch):
    monkeypatch.setattr(approval, "_execute_approved_action", lambda act, p: {"created": True})

    payload = {"key": "value"}
    app_info = approval.create_pending_approval("test_action", "Test Title", "Test Details", payload)
    
    # Reject first test request
    res_reject = approval.review_approval(app_info["id"], "rejected", "admin_user", notes="Not justified")
    assert res_reject["status"] == "rejected"
    assert res_reject["action_executed"] is False

    # Create another request and approve it
    app_info2 = approval.create_pending_approval("test_action", "Test Title 2", "Test Details", payload)
    res_approve = approval.review_approval(app_info2["id"], "approved", "admin_user", notes="Approved!")
    assert res_approve["status"] == "approved"
    assert res_approve["action_executed"] is True


def test_user_preference_memory():
    memory.set_preference("default_currency", "USD", category="procurement")
    val = memory.get_preference("default_currency")
    assert val == "USD"

    prefs = memory.list_preferences()
    assert any(p["pref_key"] == "default_currency" for p in prefs)


def test_episodic_query_pattern_memory():
    res = memory.store_query_pattern("What is total spend?", "SELECT SUM(amount) FROM vw_spend;", category="analytical")
    assert res["id"] is not None
    assert res["question"] == "What is total spend?"

    matches = memory.find_matching_query_patterns("total spend")
    assert len(matches) >= 1
