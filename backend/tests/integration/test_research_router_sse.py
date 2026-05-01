"""L1 integration tests — HTTP POST /api/v0.5/research SSE endpoint.

Tests use FastAPI TestClient (synchronous streaming) with:
  - LLM_MODE=mock via autouse fixture (inherited from integration/conftest.py)
  - get_research_graph dependency overridden with a test-scoped graph using
    stub tools + MockLLMClient (same pattern as test_research_agent_e2e_mock.py)
  - get_current_user dependency overridden with a fixed anonymous user stub

Assertions:
  1. HTTP 200 with content-type text/event-stream
  2. Every SSE line matches ``data: <json>\\n\\n`` format
  3. Each parsed event has a `type` field within the 7 allowed values
  4. At least one plan event
  5. At least one data_progress event
  6. At least one report_chunk event
  7. At least one critic_score event  (emitted when scorer_* node ends)
  8. Exactly one done event (stream terminates)
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest
from app.agents.analyst import Analyst
from app.agents.base import Agent
from app.agents.critic import Critic
from app.agents.critic_subagents.conciseness import ConcisenessScorer
from app.agents.critic_subagents.coverage import CoverageScorer
from app.agents.critic_subagents.factuality import FactualityScorer
from app.agents.critic_subagents.insight import InsightScorer
from app.agents.critic_subagents.structure import StructureScorer
from app.agents.data_collector import DataCollector
from app.agents.research_planner import ResearchPlanner
from app.agents.writer import Writer
from app.orchestration.research_graph import build_research_graph
from app.services.llm_mock_client import MockLLMClient
from app.services.llm_service import LLMService
from app.tools.base import Tool
from app.tools.registry import ToolRegistry
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

_research_mod = importlib.import_module("app.router.research")
ResearchRequest = _research_mod.ResearchRequest
ResearchStreamEvent = _research_mod.ResearchStreamEvent
get_research_graph = _research_mod.get_research_graph
get_current_user_dep = importlib.import_module("app.router.chat").get_current_user

# ---------------------------------------------------------------------------
# Fixtures dir — shared with e2e and chat router tests
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "llm_mocks"

_VALID_EVENT_TYPES = {
    "plan",
    "data_progress",
    "insight",
    "report_chunk",
    "critic_score",
    "done",
    "error",
}

# ---------------------------------------------------------------------------
# Stub tools — avoid real data dependencies in L1 tests
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Anonymous user stub
# ---------------------------------------------------------------------------


class _StubUser:
    def __init__(self) -> None:
        self.id = "test-user"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_test_research_graph() -> Any:
    """Build a full research graph wired with MockLLMClient + stub tools."""
    mock_client = MockLLMClient.from_fixture_dir(FIXTURES_DIR)
    svc = LLMService(client=mock_client)

    registry = ToolRegistry()
    registry.register(_StubQuoteTool())
    registry.register(_StubFinancialsTool())

    planner = ResearchPlanner(llm=svc)
    collector = DataCollector(llm=svc, registry=registry)
    analyst = Analyst(llm=svc)
    writer = Writer(llm=svc)
    scorers: list[Agent] = [
        FactualityScorer(llm=svc),
        CoverageScorer(llm=svc),
        InsightScorer(llm=svc),
        StructureScorer(llm=svc),
        ConcisenessScorer(llm=svc),
    ]
    critic = Critic(llm=svc, scorers=scorers)

    # No checkpointer for test isolation
    return build_research_graph(
        planner=planner,
        collector=collector,
        analyst=analyst,
        writer=writer,
        critic=critic,
        db_path=None,
    )


def _collect_sse_events(raw_body: bytes) -> list[dict[str, Any]]:
    """Parse SSE body into a list of JSON-decoded event dicts."""
    events: list[dict[str, Any]] = []
    text = raw_body.decode("utf-8")
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data: "):
            payload = line[len("data: ") :]
            events.append(json.loads(payload))
    return events


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def test_client() -> TestClient:
    """FastAPI TestClient with DI overrides for the research router tests.

    Uses a minimal FastAPI app containing only the research router so that
    legacy routers are never imported in the test context.
    """
    from app.router.research import router as research_router

    minimal_app = FastAPI()
    minimal_app.include_router(research_router)

    test_graph = _build_test_research_graph()
    minimal_app.dependency_overrides[get_research_graph] = lambda: test_graph
    minimal_app.dependency_overrides[get_current_user_dep] = lambda: _StubUser()

    client = TestClient(minimal_app, raise_server_exceptions=True)
    return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_research_sse_http_200(test_client: TestClient) -> None:
    """POST /api/v0.5/research returns HTTP 200 with text/event-stream content type."""
    resp = test_client.post(
        "/api/v0.5/research",
        json={"user_message": "深度分析茅台 600519.SH"},
        headers={"Accept": "text/event-stream"},
    )
    assert resp.status_code == 200, f"Expected 200 got {resp.status_code}: {resp.text}"
    ct = resp.headers.get("content-type", "")
    assert "text/event-stream" in ct, f"Expected text/event-stream, got {ct}"


def test_research_sse_event_framing(test_client: TestClient) -> None:
    """Every SSE line starts with 'data: ' and is valid JSON."""
    resp = test_client.post(
        "/api/v0.5/research",
        json={"user_message": "深度分析茅台 600519.SH"},
    )
    assert resp.status_code == 200

    raw = resp.content
    text = raw.decode("utf-8")
    data_lines = [line for line in text.splitlines() if line.strip()]

    n_data = len(data_lines)
    assert n_data >= 1, "Expected at least one SSE data line"

    for line in data_lines:
        line = line.strip()
        assert line.startswith("data: "), f"SSE line must start with 'data: ': {line!r}"
        payload = line[len("data: ") :]
        parsed = json.loads(payload)  # must not raise
        assert "type" in parsed, f"ResearchStreamEvent must have 'type' field: {parsed}"
        assert parsed["type"] in _VALID_EVENT_TYPES, f"Unknown event type: {parsed['type']}"


def test_research_sse_event_types_within_spec(test_client: TestClient) -> None:
    """All emitted event types are within the 7 allowed spec types."""
    events = _collect_sse_events(
        test_client.post(
            "/api/v0.5/research",
            json={"user_message": "深度分析茅台 600519.SH"},
        ).content
    )
    n = len(events)
    assert n >= 1, f"Expected >=1 SSE events, got {n}"
    for ev in events:
        assert ev["type"] in _VALID_EVENT_TYPES, f"Unexpected event type: {ev['type']}"


def test_research_sse_has_plan_event(test_client: TestClient) -> None:
    """Stream includes at least one 'plan' event (research_planner_node completed)."""
    events = _collect_sse_events(
        test_client.post(
            "/api/v0.5/research",
            json={"user_message": "深度分析茅台 600519.SH"},
        ).content
    )
    plan_events = [e for e in events if e["type"] == "plan"]
    n = len(plan_events)
    assert n >= 1, f"Expected >=1 plan event, got 0 (all events: {[e['type'] for e in events]})"


def test_research_sse_has_data_progress_event(test_client: TestClient) -> None:
    """Stream includes at least one 'data_progress' event (data_collector_node completed)."""
    events = _collect_sse_events(
        test_client.post(
            "/api/v0.5/research",
            json={"user_message": "深度分析茅台 600519.SH"},
        ).content
    )
    dp_events = [e for e in events if e["type"] == "data_progress"]
    n = len(dp_events)
    assert n >= 1, f"Expected >=1 data_progress event, got 0 (types: {[e['type'] for e in events]})"


def test_research_sse_has_report_chunk_event(test_client: TestClient) -> None:
    """Stream includes at least one 'report_chunk' event (writer_node completed)."""
    events = _collect_sse_events(
        test_client.post(
            "/api/v0.5/research",
            json={"user_message": "深度分析茅台 600519.SH"},
        ).content
    )
    rc_events = [e for e in events if e["type"] == "report_chunk"]
    n = len(rc_events)
    assert n >= 1, f"Expected >=1 report_chunk event, got 0 (types: {[e['type'] for e in events]})"


def test_research_sse_has_critic_score_event(test_client: TestClient) -> None:
    """Stream includes at least one 'critic_score' event (scorer_* node completed)."""
    events = _collect_sse_events(
        test_client.post(
            "/api/v0.5/research",
            json={"user_message": "深度分析茅台 600519.SH"},
        ).content
    )
    cs_events = [e for e in events if e["type"] == "critic_score"]
    n = len(cs_events)
    assert n >= 1, f"Expected >=1 critic_score event, got 0 (types: {[e['type'] for e in events]})"


def test_research_sse_has_done_event(test_client: TestClient) -> None:
    """Stream ends with exactly one 'done' event."""
    events = _collect_sse_events(
        test_client.post(
            "/api/v0.5/research",
            json={"user_message": "深度分析茅台 600519.SH"},
        ).content
    )
    done_events = [e for e in events if e["type"] == "done"]
    n = len(done_events)
    assert n == 1, f"Expected exactly 1 done event, got {n} (types: {[e['type'] for e in events]})"


def test_research_sse_stream_event_schema(test_client: TestClient) -> None:
    """Each SSE event validates against the ResearchStreamEvent Pydantic schema."""
    resp = test_client.post(
        "/api/v0.5/research",
        json={"user_message": "深度分析茅台 600519.SH"},
    )
    assert resp.status_code == 200

    text = resp.content.decode("utf-8")
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data: "):
            continue
        payload = json.loads(line[len("data: ") :])
        ev = ResearchStreamEvent.model_validate(payload)
        assert ev.type in _VALID_EVENT_TYPES


def test_research_request_schema_validation() -> None:
    """ResearchRequest Pydantic schema: required fields + defaults."""
    req = ResearchRequest(user_message="深度分析茅台")
    assert req.user_message == "深度分析茅台"
    assert req.target_entity == ""
    assert req.research_style == "comprehensive"


def test_research_stream_event_schema_validation() -> None:
    """ResearchStreamEvent accepts all 7 valid types."""
    for ev_type in (
        "plan",
        "data_progress",
        "insight",
        "report_chunk",
        "critic_score",
        "done",
        "error",
    ):
        ev = ResearchStreamEvent(type=ev_type, data={"key": "value"})
        assert ev.type == ev_type
