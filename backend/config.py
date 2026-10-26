"""Runtime configuration, loaded from environment / .env."""
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()  # load .env from the current working directory if present

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DUCKDB_PATH = os.path.join(HERE, "spend.duckdb")


def _resolved_duckdb_path() -> str:
    raw = os.environ.get("DUCKDB_PATH", DEFAULT_DUCKDB_PATH)
    return raw if os.path.isabs(raw) else os.path.join(HERE, raw)


@dataclass(frozen=True)
class Settings:
    slm_base_url: str = os.environ.get("ORG_SLM_BASE_URL", "")
    slm_api_key: str = os.environ.get("ORG_SLM_API_KEY", "")
    slm_model: str = os.environ.get("ORG_SLM_MODEL", "org-slm")
    duckdb_path: str = _resolved_duckdb_path()
    max_sql_retries: int = int(os.environ.get("MAX_SQL_RETRIES", "2"))
    row_limit: int = int(os.environ.get("ROW_LIMIT", "1000"))

    # SLM latency controls. The org endpoint can be slow / cold-start, so we bound
    # each call (fail fast instead of hanging for minutes) and cap generated tokens.
    slm_timeout: float = float(os.environ.get("ORG_SLM_TIMEOUT", "60"))
    slm_max_retries: int = int(os.environ.get("ORG_SLM_MAX_RETRIES", "1"))
    slm_max_tokens: int = int(os.environ.get("ORG_SLM_MAX_TOKENS", "512"))
    # The second SLM round-trip (natural-language summary) is optional and OFF by
    # default, so a question needs only ONE model call. Numbers always come from SQL.
    summarise_with_llm: bool = os.environ.get("SUMMARISE_WITH_LLM", "false").lower() in ("1", "true", "yes")
    # Fire a tiny warm-up call on startup so the first user query isn't the cold-start victim.
    warm_slm_on_start: bool = os.environ.get("WARM_SLM_ON_START", "true").lower() in ("1", "true", "yes")
    # Reasoning models (e.g. Qwen3) emit long hidden <think> traces that make every call
    # slow and can exhaust max_tokens before any answer is produced. Disable for speed.
    slm_disable_thinking: bool = os.environ.get("SLM_DISABLE_THINKING", "true").lower() in ("1", "true", "yes")

    # Contract/policy semantic search. Dense embeddings (fastembed, local ONNX — no
    # torch, no network at query time once cached) are fused with BM25 so synonyms and
    # paraphrases still retrieve the right clause. If the model can't load (offline or
    # not installed) retrieval degrades to BM25 automatically.
    doc_embeddings_enabled: bool = os.environ.get("DOC_EMBEDDINGS_ENABLED", "true").lower() in ("1", "true", "yes")
    doc_embed_model: str = os.environ.get("DOC_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
    doc_rrf_k: int = int(os.environ.get("DOC_RRF_K", "60"))


settings = Settings()
