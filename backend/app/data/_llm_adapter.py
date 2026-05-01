# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""OpenAI adapter shim for app.data layer.

Provides ``build_llm_service_from_env()`` so that legacy data-layer modules
(e.g. TushareClient) can inject an LLMService into MockTushareService without
coupling those modules to raw openai SDK usage.

Why here and not in app.services?
  app.services.* is mypy-strict and must not import openai directly.
  app.data.* is mypy ignore_errors (legacy layer), so the one-file openai
  import lives here instead of polluting strict service code.
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
    LLM_BASE_URL).  Used by TushareClient to inject into MockTushareService.
    """
    config = LLMConfig()
    model = os.getenv("MOCK_TUSHARE_MODEL", "deepseek-v3.2")
    raw_client = OpenAI(api_key=config.api_key, base_url=config.base_url)
    adapter = _OpenAIAdapter(client=raw_client, model=model)
    return LLMService(client=adapter)
