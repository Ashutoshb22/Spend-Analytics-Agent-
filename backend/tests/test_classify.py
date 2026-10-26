"""Tests for the data-classification agent (deterministic heuristic path, no SLM).

Run:  python -m pytest -q tests/test_classify.py
"""
from classify import classify_upload, profile_upload

SPEND_CSV = b"Vendor,Invoice Date,Amount,Category\nDell,2025-01-01,100,IT Hardware\nHP,2025-01-02,200,IT Hardware\n"
SUPPLIER_MASTER_CSV = b"Supplier,Address,Country,Tax ID,Payment Terms\nDell,1 St,US,123,Net30\n"
GL_CSV = b"Account,Debit,Credit,Journal,Posting Date,Period\n1000,100,0,JV1,2025-01-01,2025-01\n"


def test_profile_reads_headers():
    p = profile_upload(SPEND_CSV, "x.csv")
    assert [c.lower() for c in p["columns"]][:2] == ["vendor", "invoice date"]
    assert p["row_count"] == 2


def test_classify_spend_is_analyzable():
    r = classify_upload(SPEND_CSV, "x.csv", use_llm=False)
    assert r["is_spend"] is True
    assert r["category"] in ("Procurement Spend Ledger", "Invoices")
    assert r["method"] == "heuristic"


def test_classify_supplier_master_not_spend():
    r = classify_upload(SUPPLIER_MASTER_CSV, "s.csv", use_llm=False)
    assert r["is_spend"] is False        # no amount column -> not analysable
    assert r["category"] == "Supplier / Vendor Master"


def test_classify_general_ledger():
    r = classify_upload(GL_CSV, "gl.csv", use_llm=False)
    assert r["category"] == "General Ledger"


def test_classify_image_receipt_needs_ocr():
    r = classify_upload(b"\x89PNG\r\n\x1a\n", "receipt.png", use_llm=False)
    assert r["needs_ocr"] is True
    assert r["is_spend"] is False
    assert "image" in r["category"].lower()
