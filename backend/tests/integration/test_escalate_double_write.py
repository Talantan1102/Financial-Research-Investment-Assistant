"""L0 — escalate double-write: research_reports + ChatMessage("research_report").

Tests:
1. Happy-path: escalate_done event emitted, all 3 repos called correctly.
2. Double-write failure path: escalate_error emitted, record status→failed.

All external I/O (repos + research_agent) is mocked — no DB, no LLM.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(
    reason="legacy /api/v0/chat/escalate contract removed by the run-native router"
)

import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.router.auth_router import get_current_user_required
from app.services.eval_models import SUTOutput
from fastapi import FastAPI
from fastapi.testclient import TestClient

_OWNER_ID = uuid.uuid4()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_packet(sid: str) -> dict:
    return {
        "explicit_task": {
            "raw_last_user_turn": "深度尽调 ICBC",
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


def _collect_sse(client: TestClient, method: str, url: str, **kwargs):
    """POST to url, collect (event_type, data_dict) pairs from the SSE stream."""
    events = []
    with client.stream(method, url, **kwargs) as r:
        evt_name = None
        for line in r.iter_lines():
            if line.startswith("event:"):
                evt_name = line.removeprefix("event:").strip()
            elif line.startswith("data:") and evt_name:
                events.append((evt_name, json.loads(line.removeprefix("data:").strip())))
                evt_name = None
    return events


def _build_app(
    record_repo,
    research_agent,
    chat_repo,
    rpt_repo,
):
    from app.router.escalate import (
        get_chat_session_repo,
        get_escalation_record_repo,
        get_research_agent,
        get_research_report_repo,
        router,
    )

    # 数据隔离:record + session 都归 _OWNER_ID,认证为同一人(happy path 通过)。
    record_repo.get = AsyncMock(return_value=SimpleNamespace(session_id=uuid.uuid4()))
    chat_repo.get_session = AsyncMock(return_value=SimpleNamespace(user_id=_OWNER_ID))

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_escalation_record_repo] = lambda: record_repo
    app.dependency_overrides[get_research_agent] = lambda: research_agent
    app.dependency_overrides[get_chat_session_repo] = lambda: chat_repo
    app.dependency_overrides[get_research_report_repo] = lambda: rpt_repo
    app.dependency_overrides[get_current_user_required] = lambda: SimpleNamespace(id=_OWNER_ID)
    return app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sid():
    return str(uuid.uuid4())


@pytest.fixture
def fake_sut_output():
    return SUTOutput(
        request_id="r",
        response_text="# 工商银行尽调报告\n\n持股不动;不良率 1.36%",
        tool_calls=[],
    )


@pytest.fixture
def mocked_repos(fake_sut_output):
    from unittest.mock import MagicMock

    rpt_row = SimpleNamespace(id="rpt-abc123def456")

    record_repo = AsyncMock()
    record_repo.record_confirmation = AsyncMock(return_value=None)
    record_repo.update_status = AsyncMock(return_value=None)
    record_repo.attach_research_report = AsyncMock(return_value=None)

    chat_repo = AsyncMock()
    chat_repo.append_message = AsyncMock(return_value=None)

    rpt_repo = AsyncMock()
    rpt_repo.create_from_sut_output = AsyncMock(return_value=rpt_row)

    # run_streaming is an async generator — cannot use AsyncMock directly
    research_agent = MagicMock()

    async def _fake_streaming(user_input, request_id, **kw):
        yield {"event": "_final_sut_output", "data": fake_sut_output}

    research_agent.run_streaming = _fake_streaming

    return record_repo, research_agent, chat_repo, rpt_repo, rpt_row


# ---------------------------------------------------------------------------
# Happy-path test
# ---------------------------------------------------------------------------


def test_escalate_double_write_happy_path(sid, mocked_repos):
    record_repo, research_agent, chat_repo, rpt_repo, rpt_row = mocked_repos
    app = _build_app(record_repo, research_agent, chat_repo, rpt_repo)
    client = TestClient(app)

    payload = {
        "draft_record_id": str(uuid.uuid4()),
        "packet_confirmed": _make_packet(sid),
        "user_edits": [],
    }

    events = _collect_sse(client, "POST", "/api/v0/chat/escalate", json=payload)
    types = [e[0] for e in events]

    # escalate_done must be present, no error events
    assert "escalate_done" in types, f"Expected escalate_done; got {types}"
    assert "escalate_error" not in types, f"Unexpected error: {events}"

    done_data = next(d for t, d in events if t == "escalate_done")
    assert done_data["research_report_id"] == rpt_row.id
    assert "report_summary" in done_data
    assert "工商银行" in done_data.get("report_summary", "") or done_data["report_summary"] != ""

    # Verify all 3 double-write calls were made
    rpt_repo.create_from_sut_output.assert_awaited_once()
    chat_repo.append_message.assert_awaited_once()

    # append_message must use message_type="research_report"
    call_kwargs = chat_repo.append_message.call_args.kwargs
    assert call_kwargs.get("message_type") == "research_report"
    assert call_kwargs.get("research_report_id") == rpt_row.id

    record_repo.attach_research_report.assert_awaited_once()
    attach_kwargs = record_repo.attach_research_report.call_args
    assert attach_kwargs.kwargs.get("research_report_id") == rpt_row.id

    # update_status must eventually be called with status="completed"
    completed_calls = [
        c for c in record_repo.update_status.call_args_list if c.kwargs.get("status") == "completed"
    ]
    assert completed_calls, "update_status(status='completed') was never called"


# ---------------------------------------------------------------------------
# Failure-path test
# ---------------------------------------------------------------------------


def test_escalate_double_write_failure_path(sid, mocked_repos):
    record_repo, research_agent, chat_repo, rpt_repo, rpt_row = mocked_repos

    # Simulate create_from_sut_output blowing up
    rpt_repo.create_from_sut_output = AsyncMock(side_effect=RuntimeError("DB down"))

    app = _build_app(record_repo, research_agent, chat_repo, rpt_repo)
    client = TestClient(app)

    payload = {
        "draft_record_id": str(uuid.uuid4()),
        "packet_confirmed": _make_packet(sid),
        "user_edits": [],
    }

    events = _collect_sse(client, "POST", "/api/v0/chat/escalate", json=payload)
    types = [e[0] for e in events]

    # Must emit escalate_error, not escalate_done
    assert "escalate_error" in types, f"Expected escalate_error; got {types}"
    assert "escalate_done" not in types

    # Record must be marked failed
    failed_calls = [
        c for c in record_repo.update_status.call_args_list if c.kwargs.get("status") == "failed"
    ]
    assert failed_calls, "update_status(status='failed') was never called on double-write failure"

    # chat_repo and attach must NOT have been called (failure was at rpt creation)
    chat_repo.append_message.assert_not_awaited()
    record_repo.attach_research_report.assert_not_awaited()
