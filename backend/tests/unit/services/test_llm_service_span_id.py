"""C69 — regression test: LLMService.chat() produces unique span_ids under concurrent
calls with the same request_id, even after removal of the non-atomic _span_counter.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

import pytest
from app.services.llm_service import LLMService
from app.services.openai_client import _RawClientResponse
from app.services.trace_models import Span


@pytest.fixture(autouse=True)
def _allow_llm_service_construction(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit conftest forces LLM_MODE=none; lift it so we can construct LLMService
    with a fully-stub ChatClient (no real network).
    """
    monkeypatch.delenv("LLM_MODE", raising=False)


class _StubChatClient:
    """Minimal ChatClient stub that returns a fixed canned response."""

    def chat(self, prompt: str, model: str, schema: Any) -> _RawClientResponse:
        return _RawClientResponse(
            content="hello",
            prompt_tokens=5,
            completion_tokens=10,
        )


class _CollectingTraceService:
    """In-memory TraceService stand-in: records spans without any DB interaction.

    Used to keep this test purely L0 (no PG fixture needed).
    """

    def __init__(self) -> None:
        self._spans: list[Span] = []
        self._lock = threading.Lock()

    def write_span(self, span: Span) -> None:
        with self._lock:
            self._spans.append(span)

    @property
    def recorded(self) -> list[Span]:
        with self._lock:
            return list(self._spans)


def _build_service(collector: _CollectingTraceService) -> LLMService:
    return LLMService(
        client=_StubChatClient(),
        trace_service=collector,  # type: ignore[arg-type]  # duck-type: write_span is all LLMService calls
        cost_budget=None,
    )


# ---------------------------------------------------------------------------
# C69: span_ids must be unique across concurrent calls sharing the same request_id
# ---------------------------------------------------------------------------


def test_span_ids_unique_for_sequential_calls() -> None:
    """Sequential calls with the same request_id must produce distinct span_ids."""
    collector = _CollectingTraceService()
    svc = _build_service(collector)

    for _ in range(10):
        svc.chat(prompt="test", tier="fast", request_id="req-same")

    spans = collector.recorded
    assert len(spans) == 10
    ids = [s.span_id for s in spans]
    assert len(set(ids)) == 10, f"Duplicate span_ids detected: {ids}"


def test_span_ids_unique_under_concurrent_calls() -> None:
    """C69: Concurrent chat() calls sharing request_id='req-concurrent' must each
    produce a distinct span_id.  _span_counter was non-atomic; uuid4 per-call fixes it.
    """
    collector = _CollectingTraceService()
    svc = _build_service(collector)
    concurrency = 20

    async def _run() -> None:
        coros = [
            asyncio.to_thread(svc.chat, prompt="hi", tier="fast", request_id="req-concurrent")
            for _ in range(concurrency)
        ]
        await asyncio.gather(*coros)

    asyncio.run(_run())

    spans = collector.recorded
    assert len(spans) == concurrency
    ids = [s.span_id for s in spans]
    assert len(set(ids)) == concurrency, (
        f"Expected {concurrency} unique span_ids but got {len(set(ids))}; duplicates found"
    )


def test_span_id_prefix_matches_request_id() -> None:
    """Each span_id starts with the request_id, so it stays attributable."""
    collector = _CollectingTraceService()
    svc = _build_service(collector)

    svc.chat(prompt="hi", tier="fast", request_id="req-xyz")

    spans = collector.recorded
    assert len(spans) == 1
    assert spans[0].span_id.startswith("req-xyz-llm-"), spans[0].span_id
