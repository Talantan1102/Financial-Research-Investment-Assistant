"""L1 integration tests — HTTP POST /api/v0/chat SSE endpoint.

Tests use FastAPI TestClient (synchronous streaming) with:
  - LLM_MODE=mock via autouse fixture (inherited from integration/conftest.py)
  - get_chat_graph dependency overridden with a test-scoped graph using
    stub tools + MockLLMClient (same pattern as test_chat_agent_e2e_mock.py)
  - get_current_user dependency overridden with a fixed anonymous user stub

Assertions:
  1. HTTP 200 with content-type text/event-stream
  2. Every SSE line matches ``data: <json>\\n\\n`` format
  3. Each parsed event has a `type` field within the 6 allowed values
  4. At least one plan event
  5. At least one tool_start event
  6. At least one tool_end event
  7. Exactly one done event (stream terminates)
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from app.agents.chat_planner import ChatPlanner
from app.agents.in_session_memory import InSessionMemory
from app.agents.responder import Responder
from app.orchestration.chat_graph import build_chat_graph
from app.services.tool_result_cache import ToolResultCache

_chat_mod = importlib.import_module("app.router.chat")
ChatRequest = _chat_mod.ChatRequest
StreamEvent = _chat_mod.StreamEvent
get_chat_graph = _chat_mod.get_chat_graph
get_current_user = _chat_mod.get_current_user
get_escalation_extractor = _chat_mod.get_escalation_extractor
get_escalation_record_repo = _chat_mod.get_escalation_record_repo
from app.services.llm_mock_client import MockLLMClient
from app.services.llm_service import LLMService
from app.tools.base import Tool
from app.tools.registry import ToolRegistry
from fastapi.testclient import TestClient
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Stub tools (same pattern as test_chat_agent_e2e_mock.py)
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "llm_mocks"

_VALID_EVENT_TYPES = {"plan", "tool_start", "tool_end", "token", "done", "error"}


class _StubQuoteArgs(BaseModel):
    ts_code: str


class _StubQuoteTool(Tool):
    name = "get_stock_quote"
    description = "Return the latest daily price for a given A-share."
    args_schema = _StubQuoteArgs

    async def run(self, args: BaseModel) -> dict[str, Any]:
        validated = _StubQuoteArgs.model_validate(args.model_dump())
        return {"ts_code": validated.ts_code, "price": 1820.5, "change_pct": 0.5}


class _StubFinancialsArgs(BaseModel):
    ts_code: str
    period: str = "latest"


class _StubFinancialsTool(Tool):
    name = "get_financials"
    description = "Return revenue and net profit for a given A-share."
    args_schema = _StubFinancialsArgs

    async def run(self, args: BaseModel) -> dict[str, Any]:
        validated = _StubFinancialsArgs.model_validate(args.model_dump())
        return {"ts_code": validated.ts_code, "revenue": 1e10, "net_profit": 2e9}


class _StubNewsArgs(BaseModel):
    ts_code: str | None = None
    n: int = 5
    days_back: int = 7


class _StubNewsTool(Tool):
    name = "get_news"
    description = "Return recent news for a given A-share."
    args_schema = _StubNewsArgs

    async def run(self, args: BaseModel) -> dict[str, Any]:
        return {"items": [{"title": "stub news", "url": "https://example.com"}]}


# ---------------------------------------------------------------------------
# Anonymous user stub
# ---------------------------------------------------------------------------


class _StubUser:
    def __init__(self) -> None:
        self.id = "test-user"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_test_graph() -> Any:
    """Build a full chat graph wired with MockLLMClient + stub tools."""
    mock_client = MockLLMClient.from_fixture_dir(FIXTURES_DIR)
    svc = LLMService(client=mock_client)
    registry = ToolRegistry()
    registry.register(_StubQuoteTool())
    registry.register(_StubFinancialsTool())
    registry.register(_StubNewsTool())
    planner = ChatPlanner(llm=svc, registry=registry)
    responder = Responder(llm=svc)
    # No checkpointer for test isolation; Plan 1 signature: memory + cache required
    memory = InSessionMemory()
    cache = ToolResultCache(session_factory=MagicMock())
    return build_chat_graph(
        planner=planner, responder=responder, registry=registry, memory=memory, cache=cache
    )


def _collect_sse_events(raw_body: bytes) -> list[dict[str, Any]]:
    """Parse SSE body into a list of JSON-decoded event dicts.

    Supports the v0.9 multi-line SSE format (Plan 1):
      event: <type>
      id: <seq>
      data: <JSON without type>

    Reconstructs full event dicts with 'type' key from the event: line.
    """
    import json

    events: list[dict[str, Any]] = []
    text = raw_body.decode("utf-8")
    current_type: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("event: "):
            current_type = stripped[len("event: ") :]
        elif stripped.startswith("data: "):
            payload = json.loads(stripped[len("data: ") :])
            if current_type is not None:
                payload["type"] = current_type
            events.append(payload)
            current_type = None
    return events


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def test_client():
    """FastAPI TestClient with DI overrides for the chat router tests.

    Uses a minimal FastAPI app containing only the chat router so that legacy
    routers (document_router, research_router) — which require the bare
    ``router`` package only available under ``--app-dir backend`` — are never
    imported in the test context.
    """
    from app.router.chat import router as chat_router
    from fastapi import FastAPI

    minimal_app = FastAPI()
    minimal_app.include_router(chat_router)

    test_graph = _build_test_graph()
    minimal_app.dependency_overrides[get_chat_graph] = lambda: test_graph
    minimal_app.dependency_overrides[get_current_user] = lambda: _StubUser()
    # Plan 3 T7: stub out escalation deps so existing SSE tests aren't broken
    # by the new required dependencies. These tests don't exercise escalation.
    minimal_app.dependency_overrides[get_escalation_extractor] = lambda: None
    minimal_app.dependency_overrides[get_escalation_record_repo] = lambda: None

    client = TestClient(minimal_app, raise_server_exceptions=True)
    yield client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_chat_sse_http_200(test_client: TestClient) -> None:
    """POST /api/v0/chat returns HTTP 200 with text/event-stream content type."""
    resp = test_client.post(
        "/api/v0/chat",
        json={"session_id": "test-session-1", "message": "查一下 600519.SH 的股价"},
        headers={"Accept": "text/event-stream"},
    )
    assert resp.status_code == 200, f"Expected 200 got {resp.status_code}: {resp.text}"
    ct = resp.headers.get("content-type", "")
    assert "text/event-stream" in ct, f"Expected text/event-stream, got {ct}"


def test_chat_sse_event_framing(test_client: TestClient) -> None:
    """SSE stream uses v0.9 multi-line format: event:/id:/data: lines, valid JSON on data:."""
    import json

    resp = test_client.post(
        "/api/v0/chat",
        json={"session_id": "test-session-2", "message": "查一下 600519.SH 的股价"},
    )
    assert resp.status_code == 200

    raw = resp.content
    text = raw.decode("utf-8")
    non_empty_lines = [line.strip() for line in text.splitlines() if line.strip()]

    n_lines = len(non_empty_lines)
    assert n_lines >= 1, "Expected at least one SSE line"

    # v0.9 format: each SSE field line starts with event:, id:, or data:
    valid_prefixes = ("event: ", "id: ", "data: ")
    for line in non_empty_lines:
        assert any(line.startswith(p) for p in valid_prefixes), (
            f"SSE line must start with event:/id:/data:: {line!r}"
        )
        if line.startswith("data: "):
            json.loads(line[len("data: ") :])  # must parse as JSON

    # At least one complete event (event: + data: pair)
    events = _collect_sse_events(raw)
    assert len(events) >= 1, "Expected at least one reconstructed SSE event"
    for ev in events:
        assert "type" in ev, f"Reconstructed event must have 'type': {ev}"
        assert ev["type"] in _VALID_EVENT_TYPES, f"Unknown event type: {ev['type']}"


def test_chat_sse_event_types_within_spec(test_client: TestClient) -> None:
    """All emitted event types are within the 6 allowed spec types."""
    events = _collect_sse_events(
        test_client.post(
            "/api/v0/chat",
            json={"session_id": "test-session-3", "message": "查一下 600519.SH 的股价"},
        ).content
    )
    n = len(events)
    assert n >= 1, f"Expected ≥1 SSE events, got {n}"
    for ev in events:
        assert ev["type"] in _VALID_EVENT_TYPES, f"Unexpected event type: {ev['type']}"


def test_chat_sse_has_plan_event(test_client: TestClient) -> None:
    """Stream includes at least one 'plan' event (planner node completed)."""
    events = _collect_sse_events(
        test_client.post(
            "/api/v0/chat",
            json={"session_id": "test-session-4", "message": "查一下 600519.SH 的股价"},
        ).content
    )
    plan_events = [e for e in events if e["type"] == "plan"]
    n = len(plan_events)
    assert n >= 1, f"Expected ≥1 plan event, got 0 (all events: {[e['type'] for e in events]})"


def test_chat_sse_has_tool_start_event(test_client: TestClient) -> None:
    """Stream includes at least one 'tool_start' event."""
    events = _collect_sse_events(
        test_client.post(
            "/api/v0/chat",
            json={"session_id": "test-session-5", "message": "查一下 600519.SH 的股价"},
        ).content
    )
    tool_start_events = [e for e in events if e["type"] == "tool_start"]
    n = len(tool_start_events)
    assert n >= 1, f"Expected ≥1 tool_start event, got 0 (types: {[e['type'] for e in events]})"


def test_chat_sse_has_tool_end_event(test_client: TestClient) -> None:
    """Stream includes at least one 'tool_end' event."""
    events = _collect_sse_events(
        test_client.post(
            "/api/v0/chat",
            json={"session_id": "test-session-6", "message": "查一下 600519.SH 的股价"},
        ).content
    )
    tool_end_events = [e for e in events if e["type"] == "tool_end"]
    n = len(tool_end_events)
    assert n >= 1, f"Expected ≥1 tool_end event, got 0 (types: {[e['type'] for e in events]})"


def test_chat_sse_has_done_event(test_client: TestClient) -> None:
    """Stream ends with exactly one 'done' event."""
    events = _collect_sse_events(
        test_client.post(
            "/api/v0/chat",
            json={"session_id": "test-session-7", "message": "查一下 600519.SH 的股价"},
        ).content
    )
    done_events = [e for e in events if e["type"] == "done"]
    n = len(done_events)
    assert n == 1, f"Expected exactly 1 done event, got {n} (types: {[e['type'] for e in events]})"


def test_chat_sse_stream_event_schema(test_client: TestClient) -> None:
    """Each reconstructed SSE event validates against the StreamEvent Pydantic schema.

    v0.9 SSE format emits type on the event: line and excludes it from data: JSON.
    _collect_sse_events re-injects type so StreamEvent.model_validate succeeds.
    """
    resp = test_client.post(
        "/api/v0/chat",
        json={"session_id": "test-session-8", "message": "查一下 600519.SH 的股价"},
    )
    assert resp.status_code == 200

    events = _collect_sse_events(resp.content)
    assert len(events) >= 1, "Expected at least one SSE event"
    for payload in events:
        ev = StreamEvent.model_validate(payload)
        assert ev.type in _VALID_EVENT_TYPES


def test_chat_request_schema_validation() -> None:
    """ChatRequest Pydantic schema: required fields + defaults."""
    req = ChatRequest(session_id="abc", message="hello")
    assert req.session_id == "abc"
    assert req.message == "hello"
    assert req.enable_web_search is False
    assert req.enable_kb_search is False


def test_stream_event_schema_validation() -> None:
    """StreamEvent accepts core valid types (seq required since Plan 1 monotonic counter)."""
    for i, ev_type in enumerate(
        ("plan", "tool_start", "tool_end", "token", "done", "error"), start=1
    ):
        ev = StreamEvent(type=ev_type, seq=i, data={"key": "value"})
        assert ev.type == ev_type
