"""Shared test fixtures.

Keeps the suite hermetic: the document layer's local embedding model is never
constructed during tests (which would try to download weights), so tests run
offline and fast. Individual tests can still monkeypatch ``_embed_query`` /
``_embed_passages`` to exercise the hybrid retrieval path with fake vectors.
"""
import pytest

import documents


@pytest.fixture(autouse=True)
def _no_real_embedder(monkeypatch):
    monkeypatch.setattr(documents, "_get_embedder", lambda: None)
