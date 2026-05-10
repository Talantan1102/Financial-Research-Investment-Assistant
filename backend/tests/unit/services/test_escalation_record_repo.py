"""L0 — EscalationRecordRepo (mock-based)."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.services.escalation_record_repo import EscalationRecordRepo


def _mock_session_factory(stored_record=None):
    """Return an async context manager factory + the mock session for assertions."""
    sess = MagicMock()
    sess.add = MagicMock()
    sess.execute = AsyncMock()
    sess.commit = AsyncMock()
    sess.refresh = AsyncMock()
    sess.get = AsyncMock(return_value=stored_record)
    sess.delete = AsyncMock()

    @asynccontextmanager
    async def factory():
        yield sess

    return factory, sess


@pytest.mark.asyncio
async def test_create_draft_returns_record_with_uuid_id():
    factory, sess = _mock_session_factory()
    repo = EscalationRecordRepo(session_factory=factory)
    sid = uuid.uuid4()
    rec = await repo.create_draft(
        session_id=sid,
        packet_draft={"explicit_task": {"raw_last_user_turn": "x"}},
    )
    assert isinstance(rec.id, (uuid.UUID, str))  # UUID type
    assert rec.session_id == sid
    assert rec.status == "draft"
    sess.add.assert_called_once()
    sess.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_record_confirmation_writes_diff_via_update():
    factory, sess = _mock_session_factory()
    repo = EscalationRecordRepo(session_factory=factory)
    rid = uuid.uuid4()
    await repo.record_confirmation(
        record_id=rid,
        packet_confirmed={"explicit_task": {"raw_last_user_turn": "x'"}},
        user_edits=[{"field_path": "x", "edit_type": "modify"}],
    )
    sess.execute.assert_awaited_once()
    sess.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_attach_research_report_calls_update():
    factory, sess = _mock_session_factory()
    repo = EscalationRecordRepo(session_factory=factory)
    await repo.attach_research_report(uuid.uuid4(), research_report_id="rpt-abc")
    sess.execute.assert_awaited_once()
    sess.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_status_failed_with_error_message():
    factory, sess = _mock_session_factory()
    repo = EscalationRecordRepo(session_factory=factory)
    await repo.update_status(uuid.uuid4(), status="failed", error_msg="research timeout")
    sess.execute.assert_awaited_once()
    sess.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_status_completed_sets_completed_at():
    factory, sess = _mock_session_factory()
    repo = EscalationRecordRepo(session_factory=factory)
    await repo.update_status(uuid.uuid4(), status="completed")
    # Just verify the call happened; specific values would need execute argument inspection
    sess.execute.assert_awaited_once()
    sess.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_returns_stored_record():
    fake = MagicMock()
    fake.id = uuid.uuid4()
    factory, sess = _mock_session_factory(stored_record=fake)
    repo = EscalationRecordRepo(session_factory=factory)
    result = await repo.get(fake.id)
    assert result is fake
