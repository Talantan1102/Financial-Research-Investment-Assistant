# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

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
        r = self._client.chat.completions.create(
            model=model or self._model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            max_tokens=8000,
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
    adapter = _OpenAIAdapter(client=raw_client, model=model)
    return LLMService(client=adapter)
