"""L0/L1 — POST /api/v0/chat/escalate scaffolding."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


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


def _build_app(repo) -> FastAPI:
    from app.router.escalate import get_escalation_record_repo, router

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_escalation_record_repo] = lambda: repo
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
