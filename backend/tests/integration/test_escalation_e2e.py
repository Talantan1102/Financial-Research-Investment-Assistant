"""L0 — E2E chat→escalate→research→report wire-flow.

Covers spec § 6 industrial problems E1/E2/E11/E12/E13/E14 in one flow with
fully mocked LLM and DB layers. Real-LLM cassette comes in Plan 5.

Architecture:
- Skips wiring the chat router (covered by test_chat_router_escalate_events.py).
- Builds a minimal FastAPI app mounting only escalate_router with all deps
  overridden via dependency_overrides — no real DB, no real LLM.
- Verifies event chain via SSE stream parsing + mock call_args inspection.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.services.eval_models import SUTOutput
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# SSE helper
# ---------------------------------------------------------------------------


def _read_events(response) -> list[tuple[str, dict]]:
    """Parse (event_type, data_dict) pairs from an SSE stream response."""
    events: list[tuple[str, dict]] = []
    evt = None
    for line in response.iter_lines():
        if line.startswith("event:"):
            evt = line.removeprefix("event:").strip()
        elif line.startswith("data:") and evt:
            try:
                events.append((evt, json.loads(line.removeprefix("data:").strip())))
            except json.JSONDecodeError:
                events.append((evt, {}))
            evt = None
    return events


# ---------------------------------------------------------------------------
# Packet builder
# ---------------------------------------------------------------------------


def _build_draft_packet(sid: str) -> dict:
    return {
        "explicit_task": {
            "raw_last_user_turn": "我希望对工商银行做完整投资尽调",
            "extracted_intent": "full_due_diligence",
            "target_ts_code": "601398.SH",
            "target_entity_name": "工商银行",
            "user_extra_message": None,
        },
        "chat_derived_signals": {
            "entities": [
                {
                    "name": "工商银行",
                    "ts_code": "601398.SH",
                    "role": "primary_target",
                    "mention_turn_indices": [0],
                }
            ],
            "preferences": [
                {
                    "text": "看重资本充足率",
                    "category": "focus_metric",
                    "confidence": 0.7,
                }
            ],
            "open_questions": [],
            "inferred_persona": "bank_credit_analyst",
            "extraction_confidence": 0.75,
        },
        "known_facts": {"tool_results": []},
        "session_metadata": {
            "chat_session_id": sid,
            "chat_turn_count": 3,
            "chat_history_summary": None,
            "user_confirmed_at": datetime.now(UTC).isoformat(),
            "user_edits": [],
        },
        "missing_field_hints": [],
    }


# ---------------------------------------------------------------------------
# App builder
# ---------------------------------------------------------------------------


def _build_app(record_repo, research_agent, chat_repo, rpt_repo):
    from app.router.escalate import (
        get_chat_session_repo,
        get_escalation_record_repo,
        get_research_agent,
        get_research_report_repo,
    )
    from app.router.escalate import (
        router as escalate_router,
    )

    app = FastAPI()
    app.include_router(escalate_router)
    app.dependency_overrides[get_escalation_record_repo] = lambda: record_repo
    app.dependency_overrides[get_research_agent] = lambda: research_agent
    app.dependency_overrides[get_chat_session_repo] = lambda: chat_repo
    app.dependency_overrides[get_research_report_repo] = lambda: rpt_repo
    return app


# ---------------------------------------------------------------------------
# E2E test
# ---------------------------------------------------------------------------


def test_full_chat_escalate_research_e2e():
    """Wire escalate router with mocked agents/repos, drive escalate→research→report,
    verify event chain (E2) + all persistence calls (E11/E12/E13/E14).

    Phase 1 (chat→escalate_packet_draft) is covered by
    test_chat_router_escalate_events.py — this test starts from Phase 2:
    a user-confirmed packet POST to /api/v0/chat/escalate.
    """
    sid = str(uuid.uuid4())
    rec_id = str(uuid.uuid4())
    rpt_row = SimpleNamespace(id="rpt-abc")

    # --- Build mocked repos ---
    record_repo = AsyncMock()
    record_repo.record_confirmation = AsyncMock(return_value=None)
    record_repo.update_status = AsyncMock(return_value=None)
    record_repo.attach_research_report = AsyncMock(return_value=None)

    chat_repo = AsyncMock()
    chat_repo.append_message = AsyncMock(return_value=None)

    rpt_repo = AsyncMock()
    rpt_repo.create_from_sut_output = AsyncMock(return_value=rpt_row)

    # --- Mock research agent (async generator) ---
    research_agent = MagicMock()

    async def _research_stream(user_input, request_id, **kw):
        yield {"event": "research_planner_done", "data": {}}
        yield {"event": "research_analyst_done", "data": {}}
        yield {"event": "research_writer_done", "data": {}}
        yield {"event": "research_critic_done", "data": {}}
        yield {
            "event": "_final_sut_output",
            "data": SUTOutput(
                request_id=request_id,
                response_text="# 投资尽调报告\n\n持有; 资本充足率达标",
                tool_calls=[],
            ),
        }

    research_agent.run_streaming = _research_stream

    # --- Build app and client ---
    app = _build_app(record_repo, research_agent, chat_repo, rpt_repo)
    client = TestClient(app)

    # --- Build confirmed packet with one user edit (simulating user confirming
    # the draft that chat router would have produced in Phase 1) ---
    packet = _build_draft_packet(sid)
    packet["explicit_task"]["target_entity_name"] = "工商银行 (用户确认版)"
    user_edits = [
        {
            "field_path": "explicit_task.target_entity_name",
            "llm_value": "工商银行",
            "user_value": "工商银行 (用户确认版)",
            "edit_type": "modify",
        }
    ]

    payload = {
        "draft_record_id": rec_id,
        "packet_confirmed": packet,
        "user_edits": user_edits,
    }

    # --- Phase 2: POST /escalate and collect SSE ---
    with client.stream("POST", "/api/v0/chat/escalate", json=payload) as r:
        events = _read_events(r)

    types = [e[0] for e in events]

    # E2 — research progress events streamed through
    assert "research_planner_done" in types, f"research_planner_done missing; got {types}"
    assert "research_analyst_done" in types, f"research_analyst_done missing; got {types}"
    assert "research_writer_done" in types, f"research_writer_done missing; got {types}"
    assert "research_critic_done" in types, f"research_critic_done missing; got {types}"

    # E2 — escalate_done emitted, no error
    assert "escalate_done" in types, f"escalate_done missing; got {types}"
    assert "escalate_error" not in types, f"Unexpected escalate_error: {events}"

    # escalate_done carries report metadata
    done_data = next(d for t, d in events if t == "escalate_done")
    assert done_data["research_report_id"] == rpt_row.id
    assert "report_summary" in done_data
    assert "request_id" in done_data

    # E13 — research_report_repo.create_from_sut_output called once
    rpt_repo.create_from_sut_output.assert_awaited_once()

    # E14 — chat_session_repo.append_message called at least once (research_report ChatMessage)
    assert chat_repo.append_message.await_count >= 1
    msg_kwargs = chat_repo.append_message.call_args.kwargs
    assert msg_kwargs.get("message_type") == "research_report"
    assert msg_kwargs.get("research_report_id") == rpt_row.id

    # E12 — record_confirmation called with user_edits (all kwargs)
    record_repo.record_confirmation.assert_awaited_once()
    confirm_kwargs = record_repo.record_confirmation.call_args.kwargs
    edits_arg = confirm_kwargs.get("user_edits")
    assert edits_arg is not None, f"user_edits not in record_confirmation kwargs: {confirm_kwargs}"
    assert len(edits_arg) == 1, f"Expected 1 edit; got {edits_arg}"

    # E13 — attach_research_report called with correct report id
    record_repo.attach_research_report.assert_awaited_once()
    attach_kwargs = record_repo.attach_research_report.call_args.kwargs
    assert attach_kwargs.get("research_report_id") == rpt_row.id

    # E11 — update_status(completed) called (may be preceded by update_status(running))
    completed_calls = [
        c
        for c in record_repo.update_status.await_args_list
        if c.kwargs.get("status") == "completed"
    ]
    assert completed_calls, (
        f"update_status(status='completed') never called; "
        f"all calls: {record_repo.update_status.await_args_list}"
    )
