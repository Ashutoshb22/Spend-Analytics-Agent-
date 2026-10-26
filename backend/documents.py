"""Document intelligence: store uploaded contracts/policies and retrieve the
relevant passages — fully in-tenant (no external service, no managed vector DB).

Text is extracted (PDF/DOCX/TXT) and split into overlapping chunks kept in a
DuckDB table. Retrieval is HYBRID: a hand-rolled BM25 (great for exact terms —
contract IDs, figures, defined words) is fused with dense embeddings (great for
synonyms / paraphrases) via Reciprocal Rank Fusion, so a user who types a
different-but-related word still finds the right clause. Embeddings run locally
through fastembed (ONNX, CPU) and are stored next to the chunks; if the model
can't be loaded (offline / not installed) retrieval degrades gracefully to BM25.
"""
from __future__ import annotations

import io
import json
import math
import re
from collections import Counter

from config import settings
from db import DB_LOCK, get_ro_conn, get_rw_conn

_TOKEN = re.compile(r"[a-z0-9₹$€£%.]+")
CHUNK_SIZE = 800
CHUNK_OVERLAP = 150


def _stem(t: str) -> str:
    return t[:-1] if len(t) > 3 and t.endswith("s") else t


def _tok(text: str) -> list[str]:
    return [_stem(t) for t in _TOKEN.findall(text.lower())]


# ----------------------------------------------------------------------------
# Embeddings (optional, local — fastembed / ONNX, no torch, no network at query
# time once the model is cached). Every entry point returns None when the model
# is unavailable so retrieval can silently fall back to pure BM25.
# ----------------------------------------------------------------------------

_embedder = None
_embed_disabled = False


def _get_embedder():
    """Lazily build the local embedding model. Returns None if unavailable."""
    global _embedder, _embed_disabled
    if _embedder is not None:
        return _embedder
    if _embed_disabled or not settings.doc_embeddings_enabled:
        return None
    try:
        from fastembed import TextEmbedding

        _embedder = TextEmbedding(model_name=settings.doc_embed_model)
    except Exception:  # noqa: BLE001 - missing dep / offline / model fetch failed
        _embed_disabled = True  # don't retry for the rest of the process lifetime
        return None
    return _embedder


def _embed_passages(texts: list[str]) -> list[list[float]] | None:
    """Embed chunk texts for storage. None => embeddings unavailable."""
    emb = _get_embedder()
    if emb is None:
        return None
    try:
        return [[float(x) for x in v] for v in emb.embed(list(texts))]
    except Exception:  # noqa: BLE001
        return None


def _embed_query(query: str) -> list[float] | None:
    """Embed a search query (uses the model's query encoder when it has one)."""
    emb = _get_embedder()
    if emb is None:
        return None
    try:
        encode = getattr(emb, "query_embed", None) or emb.embed
        vecs = list(encode([query]))
        return [float(x) for x in vecs[0]] if vecs else None
    except Exception:  # noqa: BLE001
        return None


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


# ----------------------------------------------------------------------------
# Extraction & chunking
# ----------------------------------------------------------------------------

def extract_pages(filename: str, content: bytes) -> list[tuple[int, str]]:
    """Return [(page_number, text)] for a PDF / DOCX / text document."""
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(content))
        return [(i + 1, (pg.extract_text() or "")) for i, pg in enumerate(reader.pages)]
    if name.endswith((".docx", ".docm")):
        import docx

        doc = docx.Document(io.BytesIO(content))
        return [(1, "\n".join(p.text for p in doc.paragraphs))]
    # Plain text / fallback.
    return [(1, content.decode("utf-8-sig", errors="replace"))]


def _chunk_pages(pages: list[tuple[int, str]]) -> list[tuple[int, str]]:
    chunks: list[tuple[int, str]] = []
    for page, text in pages:
        text = re.sub(r"[ \t]+", " ", (text or "").replace("\r", " ")).strip()
        if not text:
            continue
        step = max(CHUNK_SIZE - CHUNK_OVERLAP, 1)
        for i in range(0, len(text), step):
            piece = text[i:i + CHUNK_SIZE].strip()
            if piece:
                chunks.append((page, piece))
    return chunks


# ----------------------------------------------------------------------------
# Storage
# ----------------------------------------------------------------------------

def _ensure(con) -> None:
    con.execute(
        "CREATE TABLE IF NOT EXISTS doc_chunks "
        "(doc_name TEXT, chunk_no INTEGER, page INTEGER, text TEXT, embedding TEXT)"
    )
    # Migrate tables created before the embedding column existed.
    cols = [r[1] for r in con.execute("PRAGMA table_info('doc_chunks')").fetchall()]
    if "embedding" not in cols:
        con.execute("ALTER TABLE doc_chunks ADD COLUMN embedding TEXT")


def add_document(filename: str, content: bytes) -> dict:
    """Extract, chunk, embed and store a document (replacing any prior copy)."""
    pages = extract_pages(filename, content)
    chunks = _chunk_pages(pages)
    if not chunks:
        raise ValueError("No readable text found in the document.")
    vectors = _embed_passages([tx for _pg, tx in chunks])  # None => BM25-only
    with DB_LOCK:
        con = get_rw_conn()
        try:
            _ensure(con)
            con.execute("DELETE FROM doc_chunks WHERE doc_name = ?", [filename])
            con.executemany(
                "INSERT INTO doc_chunks (doc_name, chunk_no, page, text, embedding) "
                "VALUES (?,?,?,?,?)",
                [
                    (filename, i, pg, tx, json.dumps(vectors[i]) if vectors else None)
                    for i, (pg, tx) in enumerate(chunks)
                ],
            )
        finally:
            con.close()
    return {
        "document": filename,
        "pages": len(pages),
        "chunks": len(chunks),
        "semantic": bool(vectors),
    }


def remove_document(filename: str) -> int:
    """Delete every chunk for a document. Returns how many chunks were removed."""
    with DB_LOCK:
        con = get_rw_conn()
        try:
            _ensure(con)
            removed = con.execute(
                "SELECT COUNT(*) FROM doc_chunks WHERE doc_name = ?", [filename]
            ).fetchone()[0]
            con.execute("DELETE FROM doc_chunks WHERE doc_name = ?", [filename])
            return int(removed or 0)
        finally:
            con.close()


def _fetch_all_chunks() -> list[tuple]:
    try:
        con = get_ro_conn()
    except Exception:  # noqa: BLE001 - db missing
        return []
    try:
        try:
            return con.execute(
                "SELECT doc_name, page, text, embedding FROM doc_chunks"
            ).fetchall()
        except Exception:  # noqa: BLE001 - pre-embedding schema
            rows = con.execute("SELECT doc_name, page, text FROM doc_chunks").fetchall()
            return [(dn, pg, tx, None) for dn, pg, tx in rows]
    except Exception:  # noqa: BLE001 - table not created yet
        return []
    finally:
        con.close()


def documents_available() -> bool:
    return bool(_fetch_all_chunks())


def list_documents() -> list[dict]:
    rows = _fetch_all_chunks()
    agg: dict[str, dict] = {}
    for row in rows:
        doc_name, page = row[0], row[1]
        d = agg.setdefault(doc_name, {"document": doc_name, "chunks": 0, "pages": 0})
        d["chunks"] += 1
        d["pages"] = max(d["pages"], page or 1)
    return list(agg.values())


# ----------------------------------------------------------------------------
# Retrieval (hybrid: BM25 + dense embeddings, fused with Reciprocal Rank Fusion)
# ----------------------------------------------------------------------------

def _norm_rows(rows: list[tuple]) -> list[tuple]:
    """Normalise fetched rows to (doc_name, page, text, embedding). The embedding
    is optional so monkeypatched 3-tuples in tests keep working."""
    return [(r[0], r[1], r[2], r[3] if len(r) > 3 else None) for r in rows]


def _load_vec(emb) -> list[float] | None:
    if not emb:
        return None
    if isinstance(emb, (list, tuple)):
        return list(emb)
    try:
        vec = json.loads(emb)
        return vec if isinstance(vec, list) else None
    except Exception:  # noqa: BLE001
        return None


def _bm25_ranking(norm: list[tuple], query: str) -> list[tuple[int, float]]:
    """Rank chunk indices by BM25 — strong on exact terms / codes / figures."""
    tokenised = [_tok(text) for (_dn, _pg, text, _emb) in norm]
    n = len(tokenised)
    if not n:
        return []
    df: Counter = Counter()
    for toks in tokenised:
        for term in set(toks):
            df[term] += 1
    idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
    avgdl = sum(len(t) for t in tokenised) / n or 1
    q_terms = _tok(query)
    k1, b = 1.5, 0.75
    scored: list[tuple[int, float]] = []
    for idx, toks in enumerate(tokenised):
        tf = Counter(toks)
        dl = len(toks)
        score = 0.0
        for qt in q_terms:
            f = tf.get(qt, 0)
            if f:
                score += idf.get(qt, 0.0) * (f * (k1 + 1)) / (f + k1 * (1 - b + b * dl / avgdl))
        if score > 0:
            scored.append((idx, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def _dense_ranking(norm: list[tuple], query: str) -> list[tuple[int, float]]:
    """Rank chunk indices by embedding cosine similarity — strong on synonyms /
    paraphrases. Empty when embeddings are unavailable on either side."""
    qvec = _embed_query(query)
    if not qvec:
        return []
    scored: list[tuple[int, float]] = []
    for idx, (_dn, _pg, _text, emb) in enumerate(norm):
        vec = _load_vec(emb)
        if not vec:
            continue
        s = _cosine(qvec, vec)
        if s > 0:
            scored.append((idx, s))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def _rrf(rankings: list[list[tuple[int, float]]], k: int) -> dict[int, float]:
    """Reciprocal Rank Fusion: combine rankings by rank, not raw score, so the
    BM25 and cosine scales never need calibrating. score = Σ 1 / (k + rank)."""
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, (idx, _s) in enumerate(ranking):
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (k + rank + 1)
    return fused


def search(query: str, k: int = 4) -> list[dict]:
    """Return the top-k most relevant chunks for a query.

    Fuses lexical (BM25) and semantic (embedding) rankings so synonyms and
    paraphrases still surface the right passage. Falls back to BM25 alone when
    embeddings are unavailable (offline / model not installed)."""
    rows = _fetch_all_chunks()
    if not rows:
        return []
    norm = _norm_rows(rows)
    bm25 = _bm25_ranking(norm, query)
    dense = _dense_ranking(norm, query)
    rankings = [bm25] + ([dense] if dense else [])
    fused = _rrf(rankings, settings.doc_rrf_k)
    if not fused:
        return []
    method = "hybrid" if dense else "bm25"
    ranked = sorted(fused.items(), key=lambda x: x[1], reverse=True)[:k]
    return [
        {
            "doc_name": norm[idx][0],
            "page": norm[idx][1],
            "text": norm[idx][2],
            "score": round(score, 4),
            "method": method,
        }
        for idx, score in ranked
    ]
