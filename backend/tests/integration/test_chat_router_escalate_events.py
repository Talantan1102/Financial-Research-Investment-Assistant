"""L1 — chat router escalation dependency stubs (Plan 3 T7).

老 supervisor 图退役(Phase 7):inline ``_stream_chat`` 升级路径已删除,升级事件
(escalate_request / escalate_packet_draft)改由 Celery worker turn 后 chunk-level
forward(见 app.tasks.chat_runner._emit_escalation,守护在
tests/integration/chatloop/test_chat_runner_loop.py)。

本文件只保留升级依赖桩(get_escalation_extractor / get_escalation_record_repo)的
wiring 守护 —— 这两个 dep stub 仍由 app_main lifespan override,escalate router 仍用。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

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
    # Stub out the user dep so the router can be instantiated
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
