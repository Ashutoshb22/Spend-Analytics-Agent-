"""Unit tests for the in-tenant document intelligence layer (documents.py).

These cover the pure extraction / chunking / tokenising helpers and the hybrid
(BM25 + dense) ranking, with the DuckDB access and the embedding model both
monkeypatched so no database is touched and no model weights are downloaded.
"""
import json

import documents


def test_extract_txt_returns_single_page():
    assert documents.extract_pages("note.txt", b"Hello world") == [(1, "Hello world")]


def test_extract_strips_bom():
    pages = documents.extract_pages("note.txt", b"\xef\xbb\xbfHello")
    assert pages[0][1] == "Hello"


def test_chunk_pages_overlaps_long_text():
    chunks = documents._chunk_pages([(1, "word " * 400)])
    assert len(chunks) >= 2
    assert all(page == 1 for page, _ in chunks)
    assert all(len(text) <= documents.CHUNK_SIZE for _, text in chunks)


def test_chunk_pages_skips_empty():
    assert documents._chunk_pages([(1, "   "), (2, "")]) == []


def test_stem_plurals_match():
    assert documents._stem("chairs") == "chair"
    assert documents._stem("is") == "is"  # too short to stem


def test_search_ranks_relevant_chunk_first(monkeypatch):
    rows = [
        ("contract.txt", 1, "The office chair unit price is 5000 per unit."),
        ("policy.txt", 2, "Travel and meal reimbursement policy for staff."),
        ("contract.txt", 3, "Laptops are billed at 1200 each under this agreement."),
    ]
    monkeypatch.setattr(documents, "_fetch_all_chunks", lambda: rows)
    hits = documents.search("did we overpay for office chairs", k=2)
    assert hits, "expected at least one hit"
    assert hits[0]["doc_name"] == "contract.txt"
    assert "chair" in hits[0]["text"].lower()
    assert hits[0]["score"] > 0


def test_search_empty_when_no_docs(monkeypatch):
    monkeypatch.setattr(documents, "_fetch_all_chunks", lambda: [])
    assert documents.search("anything") == []
    assert documents.documents_available() is False


def test_list_documents_aggregates(monkeypatch):
    rows = [("a.txt", 1, "x"), ("a.txt", 2, "y"), ("b.txt", 1, "z")]
    monkeypatch.setattr(documents, "_fetch_all_chunks", lambda: rows)
    docs = {d["document"]: d for d in documents.list_documents()}
    assert docs["a.txt"]["chunks"] == 2
    assert docs["a.txt"]["pages"] == 2
    assert docs["b.txt"]["chunks"] == 1


def test_search_hybrid_recovers_synonym(monkeypatch):
    """Dense retrieval finds a clause the user asks about with different words
    than the contract uses — the exact gap BM25 alone cannot bridge."""
    def fake_query(q: str):
        ql = q.lower()
        return [
            1.0 if any(w in ql for w in ("cancel", "terminate", "end")) else 0.0,
            1.0 if any(w in ql for w in ("price", "cost", "pay", "billed")) else 0.0,
            1.0 if "laptop" in ql else 0.0,
        ]

    rows = [
        ("contract.txt", 1,
         "Either party may terminate this agreement upon 30 days written notice.",
         json.dumps([1.0, 0.0, 0.0])),
        ("contract.txt", 2,
         "Laptops are billed at 1200 each under this agreement.",
         json.dumps([0.0, 0.0, 1.0])),
        ("policy.txt", 3,
         "Travel and meal reimbursement policy for staff.",
         json.dumps([0.0, 0.0, 0.0])),
    ]
    monkeypatch.setattr(documents, "_embed_query", fake_query)
    monkeypatch.setattr(documents, "_fetch_all_chunks", lambda: rows)

    # "cancel ... early" shares no keywords with "terminate ... notice": BM25 misses it.
    hits = documents.search("how do we cancel the contract early", k=2)
    assert hits, "expected a semantic hit"
    assert hits[0]["doc_name"] == "contract.txt"
    assert "terminate" in hits[0]["text"].lower()
    assert hits[0]["method"] == "hybrid"


def test_search_falls_back_to_bm25_without_embeddings(monkeypatch):
    """With no query embedding, retrieval still works via BM25 (graceful degrade)."""
    monkeypatch.setattr(documents, "_embed_query", lambda q: None)
    rows = [
        ("contract.txt", 1, "The office chair unit price is 5000 per unit.", None),
        ("policy.txt", 2, "Travel and meal reimbursement policy for staff.", None),
    ]
    monkeypatch.setattr(documents, "_fetch_all_chunks", lambda: rows)
    hits = documents.search("office chair price", k=2)
    assert hits and hits[0]["doc_name"] == "contract.txt"
    assert hits[0]["method"] == "bm25"
