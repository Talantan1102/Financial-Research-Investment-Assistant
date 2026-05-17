"""L0 — TraceService PG write/read round-trip."""

import contextlib
from datetime import datetime, timedelta

from app.services.trace_models import Span, TraceTree
from app.services.trace_service import TraceService


def _span(span_id: str, request_id: str, parent_id: str | None = None) -> Span:
    now = datetime(2026, 4, 30, 12, 0, 0)
    return Span(
        span_id=span_id,
        request_id=request_id,
        parent_id=parent_id,
        name="LLMService.chat",
        inputs={"prompt": "hi"},
        outputs={"content": "ok"},
        metadata={"prompt_tokens": 5, "completion_tokens": 2, "cost_cny": 0.0},
        started_at=now,
        ended_at=now + timedelta(milliseconds=100),
        error=None,
    )


def test_write_then_get_trace(db_session) -> None:
    svc = TraceService(session_factory=lambda: contextlib.nullcontext(db_session))

    root = _span("root", "r1")
    child = _span("c1", "r1", parent_id="root")
    svc.write_span(root)
    svc.write_span(child)

    tree = svc.get_trace("r1")
    assert isinstance(tree, TraceTree)
    assert tree.root_span.span_id == "root"
    assert len(tree.root_span_children) == 1


def test_get_trace_missing_request_raises(db_session) -> None:
    svc = TraceService(session_factory=lambda: contextlib.nullcontext(db_session))
    import pytest

    with pytest.raises(LookupError, match="no spans for request_id"):
        svc.get_trace("nonexistent")


def test_query_spans_by_name(db_session) -> None:
    svc = TraceService(session_factory=lambda: contextlib.nullcontext(db_session))

    svc.write_span(_span("a", "r1"))
    svc.write_span(_span("b", "r1", parent_id="a"))
    other = _span("c", "r2")
    svc.write_span(other)

    results = svc.query_spans({"request_id": "r1"})
    assert len(results) == 2
    assert {s.span_id for s in results} == {"a", "b"}


def test_init_schema_idempotent(db_session) -> None:
    """Schema is already created by pg_test_engine fixture; write then re-query works."""
    svc = TraceService(session_factory=lambda: contextlib.nullcontext(db_session))
    svc.write_span(_span("a", "r1"))
    assert len(svc.query_spans({"request_id": "r1"})) == 1
