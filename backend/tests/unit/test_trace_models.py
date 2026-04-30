"""L0 — Span / TraceTree schema invariants."""

from datetime import datetime, timedelta

import pytest
from app.services.trace_models import Span, TraceTree
from pydantic import ValidationError


def _now() -> datetime:
    return datetime(2026, 4, 30, 12, 0, 0)


def test_span_minimal() -> None:
    s = Span(
        span_id="s1",
        request_id="r1",
        parent_id=None,
        name="LLMService.chat",
        inputs={"prompt": "hi"},
        outputs={"content": "hello"},
        metadata={"tokens": 12},
        started_at=_now(),
        ended_at=_now() + timedelta(milliseconds=250),
        error=None,
    )
    assert s.latency_ms == 250
    assert s.parent_id is None


def test_span_end_before_start_rejected() -> None:
    with pytest.raises(ValidationError):
        Span(
            span_id="s1",
            request_id="r1",
            parent_id=None,
            name="x",
            inputs={},
            outputs={},
            metadata={},
            started_at=_now() + timedelta(seconds=1),
            ended_at=_now(),
            error=None,
        )


def test_tracetree_roundtrip() -> None:
    root = Span(
        span_id="root",
        request_id="r1",
        parent_id=None,
        name="ChatRequest",
        inputs={},
        outputs={},
        metadata={},
        started_at=_now(),
        ended_at=_now() + timedelta(milliseconds=400),
        error=None,
    )
    child = Span(
        span_id="c1",
        request_id="r1",
        parent_id="root",
        name="LLMService.chat",
        inputs={},
        outputs={},
        metadata={"prompt_tokens": 10, "completion_tokens": 5, "cost_cny": 0.0},
        started_at=_now() + timedelta(milliseconds=10),
        ended_at=_now() + timedelta(milliseconds=300),
        error=None,
    )
    tree = TraceTree.from_spans(spans=[root, child])
    assert tree.request_id == "r1"
    assert tree.root_span.span_id == "root"
    assert len(tree.root_span_children) == 1
    assert tree.total_latency_ms == 400


def test_tracetree_no_root_raises() -> None:
    orphan = Span(
        span_id="o1",
        request_id="r1",
        parent_id="missing",
        name="x",
        inputs={},
        outputs={},
        metadata={},
        started_at=_now(),
        ended_at=_now() + timedelta(milliseconds=10),
        error=None,
    )
    with pytest.raises(ValueError, match="no root span"):
        TraceTree.from_spans(spans=[orphan])
