"""LLMService — the single chokepoint for all LLM calls in the app.

Mode dispatch happens by injecting a different ChatClient at construction
time (mock client in L1 tests, real openai client in L2 cassette / live);
LLMService itself never branches on LLM_MODE.
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from pydantic import BaseModel

from app.services.cost_budget import CostBudget
from app.services.llm_response import LLMResponse, Tier
from app.services.pricing import compute_cost
from app.services.tier_router import TierRouter
from app.services.trace_models import Span
from app.services.trace_service import TraceService


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
        trace_service: TraceService | None = None,
        cost_budget: CostBudget | None = None,
    ) -> None:
        self._client = client
        self._tier_router = tier_router or TierRouter.from_default_v0_config()
        self._trace = trace_service
        self._budget = cost_budget
        self._span_counter: int = 0
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
        schema: dict[str, Any] | type[BaseModel] | None = None,
        request_id: str | None = None,
        parent_span_id: str | None = None,
    ) -> LLMResponse:
        if self._budget is not None:
            self._budget.assert_under_limit()  # fail-fast on PRIOR over-limit
        # v0.8.2: support Pydantic class as schema (auto-convert + auto-parse)
        pydantic_class: type[BaseModel] | None = None
        client_schema: dict[str, Any] | None
        if isinstance(schema, type) and issubclass(schema, BaseModel):
            pydantic_class = schema
            client_schema = schema.model_json_schema()
        else:
            client_schema = schema  # dict | None
        model = self._tier_router.resolve(tier)
        if request_id is None:
            request_id = f"req-{uuid4().hex[:12]}"
        started_at = datetime.now(UTC)
        started = time.perf_counter()
        raw = self._client.chat(prompt=prompt, model=model, schema=client_schema)
        latency_ms = int((time.perf_counter() - started) * 1000)
        ended_at = datetime.now(UTC)
        cost_cny = compute_cost(
            model=model,
            prompt_tokens=raw.prompt_tokens,
            completion_tokens=raw.completion_tokens,
        )
        if self._budget is not None:
            self._budget.track(cost_cny)
        response = LLMResponse(
            content=raw.content,
            parsed=pydantic_class.model_validate_json(raw.content) if pydantic_class else None,
            model=model,
            tier=tier,
            prompt_tokens=raw.prompt_tokens,
            completion_tokens=raw.completion_tokens,
            total_tokens=raw.prompt_tokens + raw.completion_tokens,
            cost_cny=cost_cny,
            latency_ms=latency_ms,
            request_id=request_id,
        )
        if self._trace is not None:
            self._span_counter += 1
            span = Span(
                span_id=f"{request_id}-llm-{self._span_counter}",
                request_id=request_id,
                parent_id=parent_span_id,
                name="LLMService.chat",
                inputs={"prompt": prompt, "tier": tier, "schema": schema},
                outputs={"content": raw.content, "model": model},
                metadata={
                    "prompt_tokens": raw.prompt_tokens,
                    "completion_tokens": raw.completion_tokens,
                    "total_tokens": raw.prompt_tokens + raw.completion_tokens,
                    "cost_cny": cost_cny,
                    "cache_hit": False,
                    "tier": tier,
                },
                started_at=started_at,
                ended_at=ended_at,
                error=None,
            )
            self._trace.write_span(span)
        return response
