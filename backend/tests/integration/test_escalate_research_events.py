"""L0/L1 — escalate endpoint streams research_* events (Task 15 / E2).

Verifies that the 4 research node events (planner/analyst/writer/critic) are
streamed before the final escalate_done event when using run_streaming.

All external I/O (repos + research_agent) is mocked — no DB, no LLM.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.services.eval_models import SUTOutput
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_packet():
    sid = str(uuid.uuid4())
    return sid, {
        "explicit_task": {
            "raw_last_user_turn": "尽调 ICBC",
            "extracted_intent": "full_due_diligence",
            "target_ts_code": "601398.SH",
            "target_entity_name": "工商银行",
            "user_extra_message": None,
        },
        "chat_derived_signals": {
            "entities": [],
            "preferences": [],
            "open_questions": [],
            "inferred_persona": None,
            "extraction_confidence": 0.7,
        },
        "known_facts": {"tool_results": []},
        "session_metadata": {
            "chat_session_id": sid,
            "chat_turn_count": 1,
            "chat_history_summary": None,
            "user_confirmed_at": datetime.now(UTC).isoformat(),
            "user_edits": [],
        },
        "missing_field_hints": [],
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _collect_sse(client: TestClient, url: str, payload: dict):
    """POST to url, collect (event_type, data_dict) pairs from the SSE stream."""
    events = []
    with client.stream("POST", url, json=payload) as r:
        evt_name = None
        for line in r.iter_lines():
            if line.startswith("event:"):
                evt_name = line.removeprefix("event:").strip()
            elif line.startswith("data:") and evt_name:
                events.append((evt_name, json.loads(line.removeprefix("data:").strip())))
                evt_name = None
    return events


def _build_app(record_repo, research_agent, chat_repo, rpt_repo):
    from app.router.escalate import (
        get_chat_session_repo,
        get_escalation_record_repo,
        get_research_agent,
        get_research_report_repo,
        router,
    )

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_escalation_record_repo] = lambda: record_repo
    app.dependency_overrides[get_research_agent] = lambda: research_agent
    app.dependency_overrides[get_chat_session_repo] = lambda: chat_repo
    app.dependency_overrides[get_research_report_repo] = lambda: rpt_repo
    return app


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_escalate_streams_research_events(fake_packet):
    """All 4 research node events should appear in the stream before escalate_done."""
    sid, packet = fake_packet

    record_repo = AsyncMock()
    record_repo.record_confirmation = AsyncMock(return_value=None)
    record_repo.update_status = AsyncMock(return_value=None)
    record_repo.attach_research_report = AsyncMock(return_value=None)

    chat_repo = AsyncMock()
    chat_repo.append_message = AsyncMock(return_value=None)

    rpt_row = SimpleNamespace(id="rpt-abc")
    rpt_repo = AsyncMock()
    rpt_repo.create_from_sut_output = AsyncMock(return_value=rpt_row)

    # Fake agent emitting all 4 node events + final output
    research_agent = MagicMock()

    async def _fake_streaming(user_input, request_id, **kw):
        yield {"event": "research_planner_done", "data": {"name": "research_planner_node"}}
        yield {"event": "research_analyst_done", "data": {"name": "analyst_node"}}
        yield {"event": "research_writer_done", "data": {"name": "writer_node"}}
        yield {"event": "research_critic_done", "data": {"name": "critic_node"}}
        yield {
            "event": "_final_sut_output",
            "data": SUTOutput(
                request_id=request_id,
                response_text="# 报告\n\n持有",
                tool_calls=[],
            ),
        }

    research_agent.run_streaming = _fake_streaming

    app = _build_app(record_repo, research_agent, chat_repo, rpt_repo)
    client = TestClient(app)

    payload = {
        "draft_record_id": str(uuid.uuid4()),
        "packet_confirmed": packet,
        "user_edits": [],
    }

    events = _collect_sse(client, "/api/v0/chat/escalate", payload)
    types = [e[0] for e in events]

    # All 4 research node events must be streamed before escalate_done
    assert "research_planner_done" in types, f"Missing research_planner_done; got {types}"
    assert "research_analyst_done" in types, f"Missing research_analyst_done; got {types}"
    assert "research_writer_done" in types, f"Missing research_writer_done; got {types}"
    assert "research_critic_done" in types, f"Missing research_critic_done; got {types}"
    assert "escalate_done" in types, f"Missing escalate_done; got {types}"
    assert "escalate_error" not in types, f"Unexpected error: {events}"

    # Research events must appear before escalate_done
    done_idx = types.index("escalate_done")
    for research_event in (
        "research_planner_done",
        "research_analyst_done",
        "research_writer_done",
        "research_critic_done",
    ):
        assert types.index(research_event) < done_idx, (
            f"{research_event} must appear before escalate_done"
        )


def test_escalate_streams_tool_events(fake_packet):
    """Tool start/end events should also be relayed when emitted."""
    sid, packet = fake_packet

    record_repo = AsyncMock()
    record_repo.record_confirmation = AsyncMock(return_value=None)
    record_repo.update_status = AsyncMock(return_value=None)
    record_repo.attach_research_report = AsyncMock(return_value=None)

    chat_repo = AsyncMock()
    chat_repo.append_message = AsyncMock(return_value=None)

    rpt_row = SimpleNamespace(id="rpt-xyz")
    rpt_repo = AsyncMock()
    rpt_repo.create_from_sut_output = AsyncMock(return_value=rpt_row)

    research_agent = MagicMock()

    async def _fake_streaming_with_tools(user_input, request_id, **kw):
        yield {"event": "research_planner_done", "data": {"name": "research_planner_node"}}
        yield {"event": "research_tool_start", "data": {"tool": "get_financial_data"}}
        yield {"event": "research_tool_end", "data": {"tool": "get_financial_data"}}
        yield {"event": "research_analyst_done", "data": {"name": "analyst_node"}}
        yield {"event": "research_writer_done", "data": {"name": "writer_node"}}
        yield {"event": "research_critic_done", "data": {"name": "critic_node"}}
        yield {
            "event": "_final_sut_output",
            "data": SUTOutput(
                request_id=request_id,
                response_text="# 报告",
                tool_calls=[],
            ),
        }

    research_agent.run_streaming = _fake_streaming_with_tools

    app = _build_app(record_repo, research_agent, chat_repo, rpt_repo)
    client = TestClient(app)

    payload = {
        "draft_record_id": str(uuid.uuid4()),
        "packet_confirmed": packet,
        "user_edits": [],
    }

    events = _collect_sse(client, "/api/v0/chat/escalate", payload)
    types = [e[0] for e in events]

    assert "research_tool_start" in types, f"Missing research_tool_start; got {types}"
    assert "research_tool_end" in types, f"Missing research_tool_end; got {types}"
    assert "escalate_done" in types
    assert "escalate_error" not in types


def test_escalate_error_when_stream_yields_no_final_output(fake_packet):
    """If run_streaming never yields _final_sut_output, escalate_error is emitted."""
    sid, packet = fake_packet

    record_repo = AsyncMock()
    record_repo.record_confirmation = AsyncMock(return_value=None)
    record_repo.update_status = AsyncMock(return_value=None)
    record_repo.attach_research_report = AsyncMock(return_value=None)

    chat_repo = AsyncMock()
    chat_repo.append_message = AsyncMock(return_value=None)

    rpt_row = SimpleNamespace(id="rpt-noop")
    rpt_repo = AsyncMock()
    rpt_repo.create_from_sut_output = AsyncMock(return_value=rpt_row)

    research_agent = MagicMock()

    async def _fake_streaming_no_final(user_input, request_id, **kw):
        yield {"event": "research_planner_done", "data": {"name": "research_planner_node"}}
        # No _final_sut_output yielded

    research_agent.run_streaming = _fake_streaming_no_final

    app = _build_app(record_repo, research_agent, chat_repo, rpt_repo)
    client = TestClient(app)

    payload = {
        "draft_record_id": str(uuid.uuid4()),
        "packet_confirmed": packet,
        "user_edits": [],
    }

    events = _collect_sse(client, "/api/v0/chat/escalate", payload)
    types = [e[0] for e in events]

    assert "escalate_error" in types, f"Expected escalate_error; got {types}"
    assert "escalate_done" not in types
    error_data = next(d for t, d in events if t == "escalate_error")
    assert "final output" in error_data.get("error", "").lower()
