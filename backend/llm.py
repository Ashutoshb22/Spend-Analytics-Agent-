"""Thin client for the organisation's SLM (OpenAI-compatible endpoint)."""
from openai import OpenAI

from config import settings

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        if not settings.slm_base_url or not settings.slm_api_key:
            raise RuntimeError(
                "Org SLM not configured. Set ORG_SLM_BASE_URL and ORG_SLM_API_KEY "
                "in your .env before calling the SLM."
            )
        _client = OpenAI(
            base_url=settings.slm_base_url,
            api_key=settings.slm_api_key,
            timeout=settings.slm_timeout,
            max_retries=settings.slm_max_retries,
        )
    return _client


def chat(messages: list[dict], temperature: float = 0.0, **kwargs) -> str:
    kwargs.setdefault("max_tokens", settings.slm_max_tokens)
    if settings.slm_disable_thinking:
        # vLLM-style switch to turn off reasoning traces (a large latency saver).
        extra = dict(kwargs.get("extra_body") or {})
        ctk = dict(extra.get("chat_template_kwargs") or {})
        ctk.setdefault("enable_thinking", False)
        extra["chat_template_kwargs"] = ctk
        kwargs["extra_body"] = extra
    resp = _get_client().chat.completions.create(
        model=settings.slm_model,
        messages=messages,
        temperature=temperature,
        **kwargs,
    )
    return resp.choices[0].message.content or ""
