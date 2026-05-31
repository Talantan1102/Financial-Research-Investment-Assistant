"""OpenAI adapter — moved from app.data._llm_adapter to app.services.

Provides ``build_llm_service_from_env()`` so that the HTTP router and
data-layer modules can get an LLMService backed by a real OpenAI-compatible
endpoint without coupling to raw openai SDK usage in strict-typed code.

Why not in app.services strict tier?
  This module directly imports ``openai.OpenAI``, which violates the
  constraint that ``app.router.chat`` must not import openai.  The router
  imports only ``build_llm_service_from_env`` (which returns an opaque
  ``LLMService``); the openai SDK call is encapsulated here.

  mypy override for app.data.* was ignore_errors=true; this file lives in
  app.services.* (strict for disallow_untyped_defs) but openai stubs are
  covered by ignore_missing_imports=true at the global level, so type-checks
  pass without an explicit ignore.
"""

from __future__ import annotations

import os

from openai import OpenAI

from app.config.llm_config import LLMConfig
from app.services.llm_service import LLMService


class _Raw:
    """Minimal ChatCompletionRaw adapter (satisfies LLMService.ChatCompletionRaw protocol)."""

    def __init__(self, content: str, prompt_tokens: int, completion_tokens: int) -> None:
        self.content = content
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


# Public alias for use in tests that need a concrete ChatCompletionRaw-compatible type.
_RawClientResponse = _Raw


class _OpenAIAdapter:
    """Thin wrapper around openai.OpenAI that satisfies the ChatClient protocol."""

    def __init__(self, client: OpenAI, model: str) -> None:
        self._client = client
        self._model = model

    def chat(self, prompt: str, model: str, schema: object) -> _Raw:  # noqa: ANN001
        # schema=None → 纯文本调用(如 chat-title 异步生成);schema 非空 → JSON 模式。
        # DashScope 当 response_format=json_object 时要求 prompt 含 "json" 字,
        # 不该强加给纯文本任务。
        common = {
            "model": model or self._model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 8000,
        }
        if schema is None:
            r = self._client.chat.completions.create(**common)  # type: ignore[call-overload]
        else:
            r = self._client.chat.completions.create(  # type: ignore[call-overload]
                **common,
                response_format={"type": "json_object"},
            )
        return _Raw(
            content=r.choices[0].message.content or "",
            prompt_tokens=r.usage.prompt_tokens if r.usage else 0,
            completion_tokens=r.usage.completion_tokens if r.usage else 0,
        )


def build_llm_service_from_env() -> LLMService:
    """Construct an LLMService backed by a real OpenAI-compatible endpoint.

    Reads API credentials from environment via LLMConfig (DASHSCOPE_API_KEY /
    LLM_BASE_URL).  Used by the HTTP chat router and TushareClient to inject
    into MockTushareService.
    """
    config = LLMConfig()
    model = os.getenv("MOCK_TUSHARE_MODEL", "deepseek-v4-flash")
    raw_client = OpenAI(api_key=config.api_key, base_url=config.base_url)
    # LangSmith 追踪(P0):LANGSMITH_TRACING=true 时把 client 包一层,自动把每次 LLM
    # 调用的 prompt/completion/token/latency 作为 run 发到 LangSmith。包装锁在这个 DI
    # 缝里 —— router / strict 层既不感知 openai 也不感知 langsmith;关时零开销。
    if os.getenv("LANGSMITH_TRACING", "").strip().lower() in {"true", "1", "yes"}:
        from langsmith.wrappers import wrap_openai

        raw_client = wrap_openai(raw_client)
    adapter = _OpenAIAdapter(client=raw_client, model=model)
    return LLMService(client=adapter)
