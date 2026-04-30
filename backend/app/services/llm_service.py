"""LLMService — the single chokepoint for all LLM calls in the app.

Mode dispatch happens by injecting a different ChatClient at construction
time (mock client in L1 tests, real openai client in L2 cassette / live);
LLMService itself never branches on LLM_MODE.
"""

from __future__ import annotations

import os
import time
from typing import Any, Protocol

from app.services.llm_response import LLMResponse, Tier
from app.services.tier_router import TierRouter


class ChatCompletionRaw(Protocol):
    """Minimal subset of openai.types.ChatCompletion that we depend on.

    Keeps LLMService from coupling to openai-specific types so MockLLMClient
    can return a plain object satisfying this shape.
    """

    @property
    def content(self) -> str: ...

    @property
    def prompt_tokens(self) -> int: ...

    @property
    def completion_tokens(self) -> int: ...


class ChatClient(Protocol):
    """Anything LLMService can drive — real openai client wrapper or mock."""

    def chat(
        self,
        prompt: str,
        model: str,
        schema: dict[str, Any] | None,
    ) -> ChatCompletionRaw: ...


class LLMService:
    def __init__(
        self,
        client: ChatClient,
        tier_router: TierRouter | None = None,
    ) -> None:
        self._client = client
        self._tier_router = tier_router or TierRouter.from_default_v0_config()
        if os.getenv("LLM_MODE") == "none":
            raise RuntimeError(
                "LLMService instantiated under LLM_MODE=none — L0 unit tests "
                "must not construct LLMService. Use TierRouter / LLMResponse "
                "directly, or mark the test as integration."
            )

    def chat(
        self,
        prompt: str,
        tier: Tier = "fast",
        schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        model = self._tier_router.resolve(tier)
        started = time.perf_counter()
        raw = self._client.chat(prompt=prompt, model=model, schema=schema)
        latency_ms = int((time.perf_counter() - started) * 1000)
        return LLMResponse(
            content=raw.content,
            parsed=None,
            model=model,
            tier=tier,
            prompt_tokens=raw.prompt_tokens,
            completion_tokens=raw.completion_tokens,
            total_tokens=raw.prompt_tokens + raw.completion_tokens,
            cost_cny=0.0,
            latency_ms=latency_ms,
        )
