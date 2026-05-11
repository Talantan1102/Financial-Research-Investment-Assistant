"""L1 — failure matrix LLM extraction max-3 retry + alert.

Per shared contract § 12: real PG required for JSONB accumulation behavior;
relocated from plan-stated unit path to integration so pg_memory_fixture is
resolvable. Test surface unchanged.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.memory.failure_matrix import (
    MAX_EXTRACTION_RETRIES,
    mark_episode_extraction_alerted,
    record_extraction_failure,
    should_retry_extraction,
)
from app.memory.models import ChatMemoryEpisode
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("SKIP_PG_TESTS") == "1",
        reason="PG container required",
    ),
]


def _make_user_session(pg_memory_fixture: dict[str, Any]) -> tuple[UUID, UUID]:
    """seed users + chat_sessions row for FK constraints."""
    engine = pg_memory_fixture["engine"]
    user_uuid = uuid4()
    session_uuid = uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, username, email, hashed_password, is_active) "
                "VALUES (:id, :u, :e, :p, true)"
            ),
            {
                "id": str(user_uuid),
                "u": f"fm_{user_uuid.hex[:8]}",
                "e": f"{user_uuid.hex[:8]}@test.local",
                "p": "x",
            },
        )
        conn.execute(
            text("INSERT INTO chat_sessions (id, user_id, title) VALUES (:id, :uid, :title)"),
            {
                "id": str(session_uuid),
                "uid": str(user_uuid),
                "title": "fm test session",
            },
        )
    return user_uuid, session_uuid


def _make_episode_in_session(pg_memory_fixture: dict[str, Any]) -> tuple[Any, UUID]:
    """L1 helper — 在真 PG 建一条最小 episode (with valid FK)."""
    engine = pg_memory_fixture["engine"]
    user_uuid, session_uuid = _make_user_session(pg_memory_fixture)
    SessionLocal = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    sess = SessionLocal()
    try:
        ep = ChatMemoryEpisode(
            episode_id=uuid4(),
            user_id=user_uuid,
            session_id=session_uuid,
            episode_index=0,
            user_message_text="test",
            source_kind="chat_turn",
            created_at=datetime.now(tz=UTC),
        )
        sess.add(ep)
        sess.commit()
        eid: UUID = ep.episode_id  # type: ignore[assignment]
        return SessionLocal, eid
    finally:
        sess.close()


def test_record_first_failure_writes_metadata_and_allows_retry(
    pg_memory_fixture: dict[str, Any],
) -> None:
    SessionLocal, eid = _make_episode_in_session(pg_memory_fixture)
    sess = SessionLocal()
    try:
        record_extraction_failure(sess, eid, failure_kind="invalid_json", error_msg="bad parse")
        sess.commit()
        assert should_retry_extraction(sess, eid) is True
    finally:
        sess.close()


def test_third_failure_marks_alerted_and_blocks_retry(
    pg_memory_fixture: dict[str, Any],
) -> None:
    SessionLocal, eid = _make_episode_in_session(pg_memory_fixture)
    sess = SessionLocal()
    try:
        for _ in range(MAX_EXTRACTION_RETRIES):
            record_extraction_failure(sess, eid, failure_kind="invalid_json", error_msg="x")
            sess.commit()
        # 第 3 次累计后,达到 max → should_retry False
        assert should_retry_extraction(sess, eid) is False
        # 标 alerted
        mark_episode_extraction_alerted(sess, eid)
        sess.commit()
        assert should_retry_extraction(sess, eid) is False
    finally:
        sess.close()


def test_extraction_metadata_accumulates_history(
    pg_memory_fixture: dict[str, Any],
) -> None:
    """metadata.failure_history 累积每次失败 entry."""
    SessionLocal, eid = _make_episode_in_session(pg_memory_fixture)
    sess = SessionLocal()
    try:
        record_extraction_failure(sess, eid, failure_kind="invalid_json", error_msg="e1")
        record_extraction_failure(sess, eid, failure_kind="llm_timeout", error_msg="e2")
        sess.commit()
        ep = sess.get(ChatMemoryEpisode, eid)
        assert ep is not None
        meta = dict(ep.extraction_metadata or {})
        history = meta.get("failure_history", [])
        assert len(history) == 2
        assert history[0]["failure_kind"] == "invalid_json"
        assert history[1]["failure_kind"] == "llm_timeout"
        assert meta.get("retry_count") == 2
    finally:
        sess.close()


def test_already_extracted_episode_does_not_retry(
    pg_memory_fixture: dict[str, Any],
) -> None:
    """extracted_at 已设置 → should_retry returns False (已抽过不重抽)."""
    SessionLocal, eid = _make_episode_in_session(pg_memory_fixture)
    sess = SessionLocal()
    try:
        ep = sess.get(ChatMemoryEpisode, eid)
        assert ep is not None
        ep.extracted_at = datetime.now(tz=UTC)
        sess.commit()
        assert should_retry_extraction(sess, eid) is False
    finally:
        sess.close()


def test_unknown_episode_does_not_retry(pg_memory_fixture: dict[str, Any]) -> None:
    """episode 不存在 → should_retry False, record_extraction_failure no-op."""
    engine = pg_memory_fixture["engine"]
    SessionLocal = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    sess = SessionLocal()
    try:
        unknown_eid = uuid4()
        assert should_retry_extraction(sess, unknown_eid) is False
        # No exception
        record_extraction_failure(sess, unknown_eid, failure_kind="invalid_json", error_msg="x")
        sess.commit()
    finally:
        sess.close()
