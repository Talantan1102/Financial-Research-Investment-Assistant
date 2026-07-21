"""L0/L1 — POST /api/v0/chat/escalate scaffolding."""

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
from fastapi import FastAPI
from fastapi.testclient import TestClient

_OWNER_ID = uuid.uuid4()


@pytest.fixture
def fake_packet_dict():
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
            "chat_session_id": "chat-1",
            "chat_turn_count": 3,
            "chat_history_summary": None,
            "user_confirmed_at": datetime.now(UTC).isoformat(),
            "user_edits": [],
        },
        "missing_field_hints": [],
    }


def _build_app(repo, research_agent=None, *, auth_user_id=_OWNER_ID, owner_id=_OWNER_ID) -> FastAPI:
    from unittest.mock import AsyncMock, MagicMock

    from app.router.escalate import (
        get_chat_session_repo,
        get_escalation_record_repo,
        get_research_agent,
        get_research_report_repo,
        router,
    )

    if research_agent is None:
        from app.services.eval_models import SUTOutput

        research_agent = MagicMock()

        async def _fake_streaming(user_input, request_id, **kw):
            yield {
                "event": "_final_sut_output",
                "data": SUTOutput(request_id="r", response_text="(report)", tool_calls=[]),
            }

        research_agent.run_streaming = _fake_streaming

    # 数据隔离:draft record 经 session_id 归属;默认 record + session 都归 owner_id。
    repo.get = AsyncMock(return_value=SimpleNamespace(session_id=uuid.uuid4()))

    # Stub chat_session_repo: append_message no-op;get_session 返回 owner 持有的会话。
    stub_chat_repo = MagicMock()
    stub_chat_repo.append_message = AsyncMock(return_value=None)
    stub_chat_repo.get_session = AsyncMock(return_value=SimpleNamespace(user_id=owner_id))

    # Stub research_report_repo: create_from_sut_output returns a fake row
    stub_rpt_row = MagicMock()
    stub_rpt_row.id = "fake-rpt-id"
    stub_rpt_repo = MagicMock()
    stub_rpt_repo.create_from_sut_output = AsyncMock(return_value=stub_rpt_row)

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_escalation_record_repo] = lambda: repo
    app.dependency_overrides[get_research_agent] = lambda: research_agent
    app.dependency_overrides[get_chat_session_repo] = lambda: stub_chat_repo
    app.dependency_overrides[get_research_report_repo] = lambda: stub_rpt_repo
    app.dependency_overrides[get_current_user_required] = lambda: SimpleNamespace(id=auth_user_id)
    return app


def test_escalate_request_pydantic_validates(fake_packet_dict):
    from app.router.escalate import EscalateRequest

    req = EscalateRequest(
        draft_record_id=uuid.uuid4(),
        packet_confirmed=fake_packet_dict,
        user_edits=[],
    )
    assert isinstance(req.draft_record_id, (uuid.UUID, str))


def test_escalate_endpoint_writes_record_and_streams(fake_packet_dict):
    repo = AsyncMock()
    repo.record_confirmation = AsyncMock(return_value=None)

    app = _build_app(repo)
    client = TestClient(app)

    payload = {
        "draft_record_id": str(uuid.uuid4()),
        "packet_confirmed": fake_packet_dict,
        "user_edits": [
            {
                "field_path": "explicit_task.target_ts_code",
                "llm_value": "601398.SH",
                "user_value": "601398.SH",
                "edit_type": "modify",
            },
        ],
    }
    with client.stream("POST", "/api/v0/chat/escalate", json=payload) as r:
        events = []
        evt = None
        for line in r.iter_lines():
            if line.startswith("event:"):
                evt = line.removeprefix("event:").strip()
            elif line.startswith("data:") and evt:
                events.append((evt, json.loads(line.removeprefix("data:").strip())))

    types = [e[0] for e in events]
    assert "escalate_done" in types
    repo.record_confirmation.assert_awaited_once()


def test_escalate_endpoint_invalid_packet_returns_422(fake_packet_dict):
    repo = AsyncMock()
    app = _build_app(repo)
    client = TestClient(app)

    payload = {
        "draft_record_id": str(uuid.uuid4()),
        "packet_confirmed": {"explicit_task": "not-a-dict"},
        "user_edits": [],
    }
    r = client.post("/api/v0/chat/escalate", json=payload)
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Data isolation — escalate rejects cross-user records/sessions (404) + needs auth
# ---------------------------------------------------------------------------


def test_escalate_404_when_session_not_owned(fake_packet_dict):
    """draft record 的会话归 owner,但认证为另一个用户 → 404,且不触发研报。"""
    repo = AsyncMock()
    repo.record_confirmation = AsyncMock(return_value=None)
    app = _build_app(repo, auth_user_id=uuid.uuid4())  # different from owner
    client = TestClient(app)

    payload = {
        "draft_record_id": str(uuid.uuid4()),
        "packet_confirmed": fake_packet_dict,
        "user_edits": [],
    }
    r = client.post("/api/v0/chat/escalate", json=payload)
    assert r.status_code == 404
    repo.record_confirmation.assert_not_awaited()


def test_escalate_401_without_auth(fake_packet_dict):
    """No token → get_current_user_required → 401."""
    from app.core.database import get_db

    repo = AsyncMock()
    app = _build_app(repo)
    app.dependency_overrides.pop(get_current_user_required, None)

    def _dummy_db():
        yield None

    app.dependency_overrides[get_db] = _dummy_db
    client = TestClient(app)

    payload = {
        "draft_record_id": str(uuid.uuid4()),
        "packet_confirmed": fake_packet_dict,
        "user_edits": [],
    }
    r = client.post("/api/v0/chat/escalate", json=payload)
    assert r.status_code == 401
