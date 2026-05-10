"""L1 — /api/v0/chat SSE event sequence (spec § 4.6).

Tests in this module are intentionally lightweight (no real graph / LLM):
- Schema validation of StreamEvent (all v0.9 event types + seq field).
- Monotonic seq counter via direct call to _stream_chat with a mocked graph.

Full end-to-end curl smoke (real FastAPI + real LangGraph) is covered in Task 21.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Schema tests (no I/O)
# ---------------------------------------------------------------------------


def test_stream_event_schema_accepts_v0_9_types() -> None:
    """Schema accepts all v0.9 event types per spec § 4.6."""
    from app.router.chat import StreamEvent

    all_types = (
        # chat-mode
        "token",
        "plan",
        "tool_start",
        "tool_end",
        "tool_error",
        "skill_load",
        "escalate_request",
        "escalate_packet_draft",
        # research-subgraph
        "research_planner_done",
        "research_tool_start",
        "research_tool_end",
        "research_analyst_done",
        "research_writer_done",
        "research_critic_done",
        "escalate_done",
        "escalate_error",
        # cross-cutting
        "cost_update",
        "done",
        "error",
    )
    for t in all_types:
        evt = StreamEvent(type=t, seq=1, data={})  # type: ignore[arg-type]
        assert evt.type == t, f"type round-trip failed for {t!r}"
        assert evt.seq == 1


def test_stream_event_seq_required() -> None:
    """seq is mandatory for SSE reconnect (spec § 4.6 / G1)."""
    from app.router.chat import StreamEvent
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        StreamEvent(type="token", data={"text": "x"})  # type: ignore[call-arg]


def test_stream_event_seq_in_serialized_json() -> None:
    """seq must survive model_dump_json round-trip."""
    from app.router.chat import StreamEvent

    evt = StreamEvent(type="done", seq=42, data={"output": {}})
    payload = json.loads(evt.model_dump_json())
    assert payload["seq"] == 42
    assert payload["type"] == "done"


def test_stream_event_exclude_type_for_sse_data() -> None:
    """model_dump_json(exclude={'type'}) keeps seq + data for the data: line."""
    from app.router.chat import StreamEvent

    evt = StreamEvent(type="token", seq=7, data={"text": "hello"})
    payload = json.loads(evt.model_dump_json(exclude={"type"}))
    assert "type" not in payload
    assert payload["seq"] == 7
    assert payload["data"] == {"text": "hello"}


# ---------------------------------------------------------------------------
# Monotonic seq test — mocked graph
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_chat_emits_monotonic_seq() -> None:
    """Mocked graph events → emitted SSE frames must have strictly increasing seq."""
    from app.router.chat import ChatRequest, _AnonUser, _stream_chat

    # Build a fake graph that yields three recognisable LangGraph event dicts.
    fake_lg_events = [
        {"event": "on_chain_end", "name": "planner_node", "data": {"output": {}}},
        {"event": "on_chain_start", "name": "tool_node", "data": {}},
        {"event": "on_chain_end", "name": "tool_node", "data": {"output": {}}},
        {"event": "on_chain_end", "name": "LangGraph", "data": {"output": {}}},
    ]

    async def _fake_astream_events(*args: object, **kwargs: object) -> AsyncIterator[dict]:
        for ev in fake_lg_events:
            yield ev

    mock_graph = MagicMock()
    mock_graph.astream_events = _fake_astream_events

    req = ChatRequest(session_id="test-session-1", message="hello")
    user = _AnonUser()

    # Patch GraphState so we don't need all required fields (trace_request_id etc.)
    # populated — _stream_chat only passes the dict to graph.astream_events which
    # is mocked; the schema construction itself is what we bypass here.
    mock_state = MagicMock()
    mock_state.model_dump.return_value = {}

    frames: list[str] = []
    with patch("app.router.chat.GraphState", return_value=mock_state):
        async for frame in _stream_chat(req, user, mock_graph, None, None):
            frames.append(frame)

    # We expect exactly 4 frames (plan, tool_start, tool_end, done).
    assert len(frames) == 4, f"Expected 4 frames, got {len(frames)}: {frames}"

    seqs: list[int] = []
    types: list[str] = []
    for frame in frames:
        lines = frame.strip().split("\n")
        # Parse "event: <type>" and "data: <json>"
        frame_type = next(line[len("event: ") :] for line in lines if line.startswith("event: "))
        data_line = next(line[len("data: ") :] for line in lines if line.startswith("data: "))
        payload = json.loads(data_line)
        seqs.append(payload["seq"])
        types.append(frame_type)

    # seq must be strictly monotonically increasing starting at 1.
    assert seqs == list(range(1, len(seqs) + 1)), f"Non-monotonic seq: {seqs}"
    # Event types must match the fake_lg_events mapping.
    assert types == ["plan", "tool_start", "tool_end", "done"]
