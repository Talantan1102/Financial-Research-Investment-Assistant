"""L0 — escalate endpoint failure paths (E4).

Verifies:
- Research crash → SSE escalate_error + EscalationRecord.update_status(failed).
- Double-write crash (chat append after research succeeds) → escalate_error + status=failed.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.router.auth_router import get_current_user_required
from app.services.eval_models import SUTOutput
from fastapi import FastAPI
from fastapi.testclient import TestClient

_OWNER_ID = uuid.uuid4()


def _make_packet(sid: str) -> dict:
    return {
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


def _build_app(record_repo, research_agent, chat_repo, rpt_repo) -> FastAPI:
    from app.router.escalate import (
        get_chat_session_repo,
        get_escalation_record_repo,
        get_research_agent,
        get_research_report_repo,
        router,
    )

    # 数据隔离:record + session 都归 _OWNER_ID,认证为同一人(走到失败路径而非 404)。
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


def _read_events(response):
    events: list[tuple[str, dict]] = []
    evt = None
    for line in response.iter_lines():
        if line.startswith("event:"):
            evt = line.removeprefix("event:").strip()
        elif line.startswith("data:") and evt:
            events.append((evt, json.loads(line.removeprefix("data:").strip())))
    return events


def test_research_crash_emits_escalate_error_and_marks_failed():
    sid = str(uuid.uuid4())
    rec_id = str(uuid.uuid4())

    record_repo = AsyncMock()
    record_repo.record_confirmation = AsyncMock(return_value=None)
    record_repo.update_status = AsyncMock(return_value=None)
    record_repo.attach_research_report = AsyncMock(return_value=None)

    chat_repo = AsyncMock()
    rpt_repo = AsyncMock()

    failing_agent = MagicMock()

    async def _bad_stream(*args, **kw):
        if False:
            yield  # make this an async generator
        raise RuntimeError("research planner timed out")

    failing_agent.run_streaming = _bad_stream

    app = _build_app(record_repo, failing_agent, chat_repo, rpt_repo)
    client = TestClient(app)

    payload = {
        "draft_record_id": rec_id,
        "packet_confirmed": _make_packet(sid),
        "user_edits": [],
    }
    with client.stream("POST", "/api/v0/chat/escalate", json=payload) as r:
        events = _read_events(r)

    types = [e[0] for e in events]
    assert "escalate_error" in types
    assert "escalate_done" not in types

    # status=failed marked
    failed_calls = [
        c
        for c in record_repo.update_status.await_args_list
        if c.kwargs.get("status") == "failed" or (len(c.args) >= 2 and c.args[1] == "failed")
    ]
    assert failed_calls, (
        f"expected update_status(status=failed) call; got {record_repo.update_status.await_args_list}"
    )


def test_double_write_failure_marks_record_failed():
    """If ChatMessage append fails after research succeeds, status must still be failed."""
    sid = str(uuid.uuid4())
    rec_id = str(uuid.uuid4())

    record_repo = AsyncMock()
    record_repo.record_confirmation = AsyncMock(return_value=None)
    record_repo.update_status = AsyncMock(return_value=None)
    record_repo.attach_research_report = AsyncMock(return_value=None)

    # research succeeds
    research_agent = MagicMock()

    async def _ok_stream(user_input, request_id, **kw):
        yield {"event": "research_planner_done", "data": {}}
        yield {
            "event": "_final_sut_output",
            "data": SUTOutput(
                request_id=request_id,
                response_text="# 报告\n\n持有",
                tool_calls=[],
            ),
        }

    research_agent.run_streaming = _ok_stream

    # research_report_repo succeeds
    rpt_row = SimpleNamespace(id="rpt-abc")
    rpt_repo = AsyncMock()
    rpt_repo.create_from_sut_output = AsyncMock(return_value=rpt_row)

    # chat_session_repo.append_message FAILS
    chat_repo = AsyncMock()
    chat_repo.append_message = AsyncMock(side_effect=RuntimeError("DB unavailable"))

    app = _build_app(record_repo, research_agent, chat_repo, rpt_repo)
    client = TestClient(app)

    payload = {
        "draft_record_id": rec_id,
        "packet_confirmed": _make_packet(sid),
        "user_edits": [],
    }
    with client.stream("POST", "/api/v0/chat/escalate", json=payload) as r:
        events = _read_events(r)

    types = [e[0] for e in events]
    assert "escalate_error" in types
    # status=failed marked even though research itself succeeded
    failed_calls = [
        c
        for c in record_repo.update_status.await_args_list
        if c.kwargs.get("status") == "failed" or (len(c.args) >= 2 and c.args[1] == "failed")
    ]
    assert failed_calls, (
        f"expected update_status(status=failed); got {record_repo.update_status.await_args_list}"
    )
