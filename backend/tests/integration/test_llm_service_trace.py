"""L1 — when LLMService is constructed with a TraceService, every chat
call writes one span; LLMResponse.request_id matches the span's request_id.
"""

from pathlib import Path

from app.services.llm_mock_client import MockLLMClient
from app.services.llm_service import LLMService
from app.services.trace_service import TraceService


def test_chat_writes_one_span_per_call(
    mock_llm_client: MockLLMClient,
    tmp_eval_db: Path,
) -> None:
    trace = TraceService(db_path=tmp_eval_db)
    trace.init_schema()
    svc = LLMService(client=mock_llm_client, trace_service=trace)

    r = svc.chat(prompt="What is the price of 600519.SH?", tier="fast")

    assert r.request_id is not None
    spans = trace.query_spans({"request_id": r.request_id})
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "LLMService.chat"
    assert span.metadata["tier"] == "fast"
    assert span.metadata["prompt_tokens"] == r.prompt_tokens


def test_chat_without_trace_service_writes_nothing(
    mock_llm_client: MockLLMClient,
    tmp_eval_db: Path,
) -> None:
    """Plan B contract: trace_service=None → zero side effects."""
    trace = TraceService(db_path=tmp_eval_db)
    trace.init_schema()
    svc = LLMService(client=mock_llm_client)  # no trace_service

    r = svc.chat(prompt="What is the price of 600519.SH?", tier="fast")

    assert trace.query_spans({}) == []
    assert r.content


def test_chat_with_explicit_request_id_uses_it(
    mock_llm_client: MockLLMClient,
    tmp_eval_db: Path,
) -> None:
    trace = TraceService(db_path=tmp_eval_db)
    trace.init_schema()
    svc = LLMService(client=mock_llm_client, trace_service=trace)

    r1 = svc.chat(prompt="What is the price of 600519.SH?", tier="fast", request_id="req-foo")
    r2 = svc.chat(prompt="What is the price of 600519.SH?", tier="fast", request_id="req-foo")

    assert r1.request_id == "req-foo"
    assert r2.request_id == "req-foo"
    spans = trace.query_spans({"request_id": "req-foo"})
    assert len(spans) == 2
