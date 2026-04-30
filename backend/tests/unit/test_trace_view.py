"""L0 — trace_view tree formatter pure function."""

from datetime import datetime, timedelta

from app.services.trace_models import Span, TraceTree

from scripts.trace_view import format_trace_tree


def _span(span_id: str, parent_id: str | None, name: str, latency_ms: int) -> Span:
    base = datetime(2026, 4, 30, 12, 0, 0)
    return Span(
        span_id=span_id,
        request_id="r1",
        parent_id=parent_id,
        name=name,
        inputs={},
        outputs={},
        metadata={"cost_cny": 0.001},
        started_at=base,
        ended_at=base + timedelta(milliseconds=latency_ms),
        error=None,
    )


def test_format_root_only() -> None:
    root = _span("root", None, "ChatRequest", 400)
    tree = TraceTree.from_spans([root])
    out = format_trace_tree(tree)
    assert "root" in out
    assert "ChatRequest" in out
    assert "400ms" in out


def test_format_with_children() -> None:
    root = _span("root", None, "ChatRequest", 400)
    c1 = _span("c1", "root", "LLMService.chat", 250)
    tree = TraceTree.from_spans([root, c1])
    out = format_trace_tree(tree)
    assert "ChatRequest" in out
    assert "LLMService.chat" in out
    # Child should be indented under root
    lines = out.splitlines()
    root_line_idx = next(i for i, line in enumerate(lines) if "ChatRequest" in line)
    child_line_idx = next(i for i, line in enumerate(lines) if "LLMService.chat" in line)
    assert child_line_idx > root_line_idx
    # Child line has more leading whitespace OR a tree-prefix char
    assert lines[child_line_idx].startswith(("  ", "│", "└", "├"))
