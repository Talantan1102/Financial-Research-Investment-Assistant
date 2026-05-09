"""L1 — chat router emits escalate events when planner offers escalate (Plan 3 T7).

Tests:
1. Dependency stubs are importable and callable.
2. dependency_overrides wiring works (smoke via app construction).
3. escalate_request + escalate_packet_draft are emitted when final_state
   has escalate_offered=True, extractor and repo are properly mocked.

Full end-to-end (real LangGraph + real LLM) is deferred to Plan 5 cassette.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_extractor():
    """AsyncMock EscalationExtractor whose .run() returns a minimal EscalationPacket."""
    from app.agents.escalation_extractor import EscalationExtractor
    from app.agents.escalation_protocol import (
        ChatDerivedSignals,
        EscalationPacket,
        ExplicitTask,
        KnownFacts,
        SessionMetadata,
    )

    fake_packet = EscalationPacket(
        explicit_task=ExplicitTask(
            raw_last_user_turn="深度尽调 ICBC",
            extracted_intent="full_due_diligence",
            target_ts_code="601398.SH",
            target_entity_name="工商银行",
        ),
        chat_derived_signals=ChatDerivedSignals(extraction_confidence=0.7),
        known_facts=KnownFacts(),
        session_metadata=SessionMetadata(
            chat_session_id="test-sid",
            chat_turn_count=1,
            user_confirmed_at=datetime.now(UTC),
        ),
    )

    m = AsyncMock(spec=EscalationExtractor)
    m.run = AsyncMock(return_value=fake_packet)
    return m, fake_packet


@pytest.fixture
def mock_record_repo():
    """AsyncMock EscalationRecordRepo whose .create_draft() returns a stub record."""
    record_id = uuid.uuid4()
    mock_record = SimpleNamespace(id=record_id)
    repo = AsyncMock()
    repo.create_draft = AsyncMock(return_value=mock_record)
    return repo, record_id


# ---------------------------------------------------------------------------
# Helper: build a minimal FastAPI app with escalation mocks
# ---------------------------------------------------------------------------


def _build_app_with_mocks(extractor_mock, repo_mock):
    """Build a minimal app with all chat-router deps overridden."""
    from app.router.chat import (
        get_current_user,
        get_escalation_extractor,
        get_escalation_record_repo,
        router,
    )

    app = FastAPI()
    app.include_router(router)
    # Escalation deps
    app.dependency_overrides[get_escalation_extractor] = lambda: extractor_mock
    app.dependency_overrides[get_escalation_record_repo] = lambda: repo_mock
    # Stub out the graph and user deps so the router can be instantiated
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="test-user")
    return app


# ---------------------------------------------------------------------------
# Tests: dependency stub wiring
# ---------------------------------------------------------------------------


def test_escalate_dependency_stubs_are_importable():
    """Smoke: both dep stubs are exported from chat router."""
    from app.router.chat import (
        get_escalation_extractor,
        get_escalation_record_repo,
    )

    assert callable(get_escalation_extractor)
    assert callable(get_escalation_record_repo)


def test_escalate_dependency_stubs_raise_when_not_overridden():
    """Dep stubs raise RuntimeError when called without override (safety sentinel)."""
    from app.router.chat import (
        get_escalation_extractor,
        get_escalation_record_repo,
    )

    with pytest.raises(RuntimeError, match="EscalationExtractor dependency not configured"):
        get_escalation_extractor()

    with pytest.raises(RuntimeError, match="EscalationRecordRepo dependency not configured"):
        get_escalation_record_repo()


def test_dependency_override_wiring_smoke(mock_extractor, mock_record_repo):
    """App construction with overridden deps does not raise."""
    extractor_mock, _ = mock_extractor
    repo_mock, _ = mock_record_repo
    app = _build_app_with_mocks(extractor_mock, repo_mock)
    # Should not raise; router + overrides mounted correctly
    assert app is not None


# ---------------------------------------------------------------------------
# Tests: _stream_chat escalation path (mocked graph)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_chat_emits_escalate_events_when_offered(mock_extractor, mock_record_repo):
    """_stream_chat emits escalate_request + escalate_packet_draft when escalate_offered=True."""
    from app.router.chat import ChatRequest, _AnonUser, _stream_chat

    extractor_mock, fake_packet = mock_extractor
    repo_mock, record_id = mock_record_repo

    # Fake LangGraph events: final LangGraph event has escalate_offered=True
    fake_lg_events = [
        {"event": "on_chain_end", "name": "planner_node", "data": {"output": {}}},
        {
            "event": "on_chain_end",
            "name": "LangGraph",
            "data": {
                "output": {
                    "escalate_offered": True,
                    "plan": {"escalate_reason": "User requested deep due diligence"},
                    "history": [],
                    "history_summary": None,
                    "tool_result_cache": {},
                }
            },
        },
    ]

    async def _fake_astream_events(*args, **kwargs) -> AsyncIterator[dict]:
        for ev in fake_lg_events:
            yield ev

    mock_graph = MagicMock()
    mock_graph.astream_events = _fake_astream_events

    req = ChatRequest(session_id="test-sid", message="帮我做一个工行的深度尽调")
    user = _AnonUser()

    mock_state = MagicMock()
    mock_state.model_dump.return_value = {}

    frames: list[str] = []
    with patch("app.router.chat.GraphState", return_value=mock_state):
        async for frame in _stream_chat(req, user, mock_graph, extractor_mock, repo_mock):
            frames.append(frame)

    # Extract event types from frames
    event_types = []
    for frame in frames:
        for line in frame.strip().split("\n"):
            if line.startswith("event: "):
                event_types.append(line[len("event: ") :])

    assert "escalate_request" in event_types, f"Missing escalate_request; got: {event_types}"
    assert "escalate_packet_draft" in event_types, (
        f"Missing escalate_packet_draft; got: {event_types}"
    )

    # escalate_request must come before escalate_packet_draft
    idx_req = event_types.index("escalate_request")
    idx_draft = event_types.index("escalate_packet_draft")
    assert idx_req < idx_draft, "escalate_request must precede escalate_packet_draft"


@pytest.mark.asyncio
async def test_stream_chat_no_escalate_events_when_not_offered(mock_extractor, mock_record_repo):
    """_stream_chat does NOT emit escalate events when escalate_offered=False."""
    from app.router.chat import ChatRequest, _AnonUser, _stream_chat

    extractor_mock, _ = mock_extractor
    repo_mock, _ = mock_record_repo

    fake_lg_events = [
        {"event": "on_chain_end", "name": "planner_node", "data": {"output": {}}},
        {
            "event": "on_chain_end",
            "name": "LangGraph",
            "data": {
                "output": {
                    "escalate_offered": False,
                    "history": [],
                    "history_summary": None,
                    "tool_result_cache": {},
                }
            },
        },
    ]

    async def _fake_astream_events(*args, **kwargs) -> AsyncIterator[dict]:
        for ev in fake_lg_events:
            yield ev

    mock_graph = MagicMock()
    mock_graph.astream_events = _fake_astream_events

    req = ChatRequest(session_id="test-sid-2", message="工行今天股价多少")
    user = _AnonUser()

    mock_state = MagicMock()
    mock_state.model_dump.return_value = {}

    frames: list[str] = []
    with patch("app.router.chat.GraphState", return_value=mock_state):
        async for frame in _stream_chat(req, user, mock_graph, extractor_mock, repo_mock):
            frames.append(frame)

    event_types = []
    for frame in frames:
        for line in frame.strip().split("\n"):
            if line.startswith("event: "):
                event_types.append(line[len("event: ") :])

    assert "escalate_request" not in event_types, f"Unexpected escalate_request; got: {event_types}"
    assert "escalate_packet_draft" not in event_types, (
        f"Unexpected escalate_packet_draft; got: {event_types}"
    )
    # Extractor should NOT have been called
    extractor_mock.run.assert_not_called()


@pytest.mark.asyncio
async def test_stream_chat_escalate_skipped_when_deps_none():
    """_stream_chat skips escalation events when extractor/repo are None (not wired)."""
    from app.router.chat import ChatRequest, _AnonUser, _stream_chat

    fake_lg_events = [
        {
            "event": "on_chain_end",
            "name": "LangGraph",
            "data": {"output": {"escalate_offered": True, "history": [], "tool_result_cache": {}}},
        },
    ]

    async def _fake_astream_events(*args, **kwargs) -> AsyncIterator[dict]:
        for ev in fake_lg_events:
            yield ev

    mock_graph = MagicMock()
    mock_graph.astream_events = _fake_astream_events

    req = ChatRequest(session_id="test-sid-3", message="尽调请求")
    user = _AnonUser()

    mock_state = MagicMock()
    mock_state.model_dump.return_value = {}

    frames: list[str] = []
    with patch("app.router.chat.GraphState", return_value=mock_state):
        # Pass None for both escalation deps (not yet wired scenario)
        async for frame in _stream_chat(req, user, mock_graph, None, None):
            frames.append(frame)

    event_types = []
    for frame in frames:
        for line in frame.strip().split("\n"):
            if line.startswith("event: "):
                event_types.append(line[len("event: ") :])

    # escalate events must be absent — silently skipped with a log warning
    assert "escalate_request" not in event_types
    assert "escalate_packet_draft" not in event_types


@pytest.mark.asyncio
async def test_stream_chat_escalate_emits_error_event_on_extractor_failure(mock_record_repo):
    """_stream_chat emits error event when extractor.run() raises."""
    from app.router.chat import ChatRequest, _AnonUser, _stream_chat

    repo_mock, _ = mock_record_repo

    broken_extractor = AsyncMock()
    broken_extractor.run = AsyncMock(side_effect=RuntimeError("LLM unreachable"))

    fake_lg_events = [
        {
            "event": "on_chain_end",
            "name": "LangGraph",
            "data": {
                "output": {
                    "escalate_offered": True,
                    "plan": {"escalate_reason": "deep dive"},
                    "history": [],
                    "tool_result_cache": {},
                }
            },
        },
    ]

    async def _fake_astream_events(*args, **kwargs) -> AsyncIterator[dict]:
        for ev in fake_lg_events:
            yield ev

    mock_graph = MagicMock()
    mock_graph.astream_events = _fake_astream_events

    req = ChatRequest(session_id="test-sid-4", message="尽调工行")
    user = _AnonUser()

    mock_state = MagicMock()
    mock_state.model_dump.return_value = {}

    frames: list[str] = []
    with patch("app.router.chat.GraphState", return_value=mock_state):
        async for frame in _stream_chat(req, user, mock_graph, broken_extractor, repo_mock):
            frames.append(frame)

    event_types = []
    for frame in frames:
        for line in frame.strip().split("\n"):
            if line.startswith("event: "):
                event_types.append(line[len("event: ") :])

    # Should emit escalate_request (succeeds) then error (extractor failed)
    assert "escalate_request" in event_types, f"Expected escalate_request; got: {event_types}"
    assert "error" in event_types, f"Expected error event; got: {event_types}"
    assert "escalate_packet_draft" not in event_types


@pytest.mark.asyncio
async def test_stream_chat_escalate_packet_contains_draft_record_id(
    mock_extractor, mock_record_repo
):
    """escalate_packet_draft event data includes draft_record_id + packet."""
    from app.router.chat import ChatRequest, _AnonUser, _stream_chat

    extractor_mock, fake_packet = mock_extractor
    repo_mock, record_id = mock_record_repo

    fake_lg_events = [
        {
            "event": "on_chain_end",
            "name": "LangGraph",
            "data": {
                "output": {
                    "escalate_offered": True,
                    "plan": {"escalate_reason": "full_due_diligence"},
                    "history": [],
                    "history_summary": "用户问过工行估值",
                    "tool_result_cache": {},
                }
            },
        },
    ]

    async def _fake_astream_events(*args, **kwargs) -> AsyncIterator[dict]:
        for ev in fake_lg_events:
            yield ev

    mock_graph = MagicMock()
    mock_graph.astream_events = _fake_astream_events

    req = ChatRequest(session_id="test-sid-5", message="帮我做工行深度报告")
    user = _AnonUser()

    mock_state = MagicMock()
    mock_state.model_dump.return_value = {}

    frames: list[str] = []
    with patch("app.router.chat.GraphState", return_value=mock_state):
        async for frame in _stream_chat(req, user, mock_graph, extractor_mock, repo_mock):
            frames.append(frame)

    # Find the escalate_packet_draft frame
    draft_frame = None
    for frame in frames:
        lines = frame.strip().split("\n")
        for line in lines:
            if line == "event: escalate_packet_draft":
                # Get corresponding data line
                for dl in lines:
                    if dl.startswith("data: "):
                        draft_frame = json.loads(dl[len("data: ") :])
                break

    assert draft_frame is not None, "No escalate_packet_draft frame found"
    assert "draft_record_id" in draft_frame["data"], f"Missing draft_record_id: {draft_frame}"
    assert draft_frame["data"]["draft_record_id"] == str(record_id)
    assert "packet" in draft_frame["data"], "Missing packet in escalate_packet_draft data"

    # Verify extractor was called with correct session_id
    extractor_mock.run.assert_called_once()
    call_kwargs = extractor_mock.run.call_args.kwargs
    assert call_kwargs["chat_session_id"] == "test-sid-5"
    assert call_kwargs["chat_history_summary"] == "用户问过工行估值"
