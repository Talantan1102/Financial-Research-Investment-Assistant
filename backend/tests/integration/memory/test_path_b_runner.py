"""L1 — PathBRunner 编排单测 (mock LLMExtractor + mock archival_memory_insert).

Per shared contract § 12: relocated from plan-stated unit path to integration
because the runner reads/writes real chat_memory_episodes (JSONB), needing real PG.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from app.memory.path_b_runner import PathBRunner, PathBRunResult
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("SKIP_PG_TESTS") == "1",
        reason="PG container required",
    ),
]


def _seed_user_session(pg_memory_fixture: dict[str, Any]) -> tuple[UUID, UUID]:
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
                "u": f"pbr_{user_uuid.hex[:8]}",
                "e": f"{user_uuid.hex[:8]}@test.local",
                "p": "x",
            },
        )
        conn.execute(
            text("INSERT INTO chat_sessions (id, user_id, title) VALUES (:id, :uid, :title)"),
            {
                "id": str(session_uuid),
                "uid": str(user_uuid),
                "title": "pbr",
            },
        )
    return user_uuid, session_uuid


def _make_episode(
    SessionLocal: Any,
    user_id: UUID,
    session_id: UUID,
    idx: int,
    ts: datetime,
    user_msg: str,
    agent_msg: str = "",
    source_kind: str = "chat_turn",
) -> UUID:
    from app.memory.models import ChatMemoryEpisode

    sess = SessionLocal()
    try:
        ep = ChatMemoryEpisode(
            episode_id=uuid4(),
            user_id=user_id,
            session_id=session_id,
            episode_index=idx,
            user_message_text=user_msg,
            agent_response_text=agent_msg,
            source_kind=source_kind,
            created_at=ts,
        )
        sess.add(ep)
        sess.commit()
        eid: UUID = ep.episode_id  # type: ignore[assignment]
        return eid
    finally:
        sess.close()


@pytest.mark.asyncio
async def test_path_b_permanently_excludes_agent_explicit_episode(
    pg_memory_fixture: dict[str, Any],
) -> None:
    """显式 memory_write 的审计 episode 即使未抽取，也绝不能被 Path B 二次抽取。"""
    engine = pg_memory_fixture["engine"]
    SessionLocal = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    user_id, session_id = _seed_user_session(pg_memory_fixture)
    _make_episode(
        SessionLocal,
        user_id,
        session_id,
        0,
        datetime.now(UTC),
        "我买了茅台",
        source_kind="agent_explicit",
    )
    extractor = MagicMock()
    extractor.extract_facts = AsyncMock(return_value={"entities": [], "edges": []})
    runner = PathBRunner(
        session_factory=SessionLocal,
        llm_extractor=extractor,
        archival_insert_fn=AsyncMock(),
    )

    result = await runner.run_for_session(session_id, "post_turn")

    assert result.episodes_scanned == 0
    extractor.extract_facts.assert_not_awaited()


@pytest.mark.asyncio
async def test_explicit_episode_is_atomically_claimed_and_keeps_cancel_audit(
    pg_memory_fixture: dict[str, Any],
) -> None:
    from app.memory.hierarchical import HierarchicalMemory
    from app.memory.models import ChatMemoryEpisode

    engine = pg_memory_fixture["engine"]
    SessionLocal = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    user_id, session_id = _seed_user_session(pg_memory_fixture)
    memory = HierarchicalMemory(SessionLocal, None, None, None, None, None)

    episode = await memory.write_explicit_episode(
        user_id=user_id,
        session_id=session_id,
        episode_index=0,
        user_message="我买了茅台",
        agent_response="",
    )

    assert episode.source_kind == "agent_explicit"
    assert episode.extracted_at is not None
    assert episode.extracted_by == "agent_explicit_claim"
    assert episode.extraction_metadata == {"explicit_status": "pending"}

    # 未经过 archival pipeline 的 claim 即使 runner 乐观传 completed，也必须落 failed。
    await memory.finalize_explicit_episode(episode.episode_id, "记录失败", "completed")
    sess = SessionLocal()
    try:
        persisted = sess.query(ChatMemoryEpisode).filter_by(episode_id=episode.episode_id).one()
        assert persisted.agent_response_text == "记录失败"
        assert persisted.extracted_at is not None
        assert persisted.extracted_by == "agent_explicit_failed"
        assert persisted.extraction_metadata["explicit_status"] == "failed"
    finally:
        sess.close()

    await memory.finalize_explicit_episode(episode.episode_id, "正在记录", "cancelled")
    sess = SessionLocal()
    try:
        persisted = sess.query(ChatMemoryEpisode).filter_by(episode_id=episode.episode_id).one()
        assert persisted.extracted_by == "agent_explicit_cancelled"
        assert persisted.extraction_metadata["explicit_status"] == "cancelled"
    finally:
        sess.close()


@pytest.mark.asyncio
async def test_path_b_full_path_calls_extractor_and_marks_extracted(
    pg_memory_fixture: dict[str, Any],
) -> None:
    engine = pg_memory_fixture["engine"]
    SessionLocal = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    user_id, session_id = _seed_user_session(pg_memory_fixture)
    base = datetime(2026, 5, 11, 10, 0, 0, tzinfo=UTC)
    # Plan 5 skip_gate 需要 strategy / ts_code 触发词,否则 < 50 字短消息 false-skip
    eids = [
        _make_episode(SessionLocal, user_id, session_id, 0, base, "我刚买入了股票"),
        _make_episode(
            SessionLocal,
            user_id,
            session_id,
            1,
            base + timedelta(minutes=2),
            "茅台 600519.SH",
        ),
        _make_episode(
            SessionLocal,
            user_id,
            session_id,
            2,
            base + timedelta(minutes=4),
            "500 股长期持有",
        ),
    ]

    mock_extractor = MagicMock()
    mock_extractor.extract_facts = AsyncMock(
        return_value={
            "entities": [
                {"entity_type": "Stock", "entity_label": "600519.SH", "properties": {}},
            ],
            "edges": [
                {
                    "rel_type": "HOLDS",
                    "source_label": "User",
                    "target_label": "600519.SH",
                    "valid_from": base.isoformat(),
                    "valid_to": None,
                    "importance": 0.9,
                    "reasoning": "user explicitly bought 500 shares of moutai",
                    "evidence_quote": "茅台 600519, 500 股",
                    "properties": {"qty": 500},
                    "source_episode_id": str(eids[2]),  # 跨 turn fact 归属第 3 turn
                }
            ],
        }
    )
    archival_calls: list[dict[str, Any]] = []

    async def fake_insert(**kwargs: Any) -> Any:
        archival_calls.append(kwargs)
        return MagicMock(edge_id=uuid4())

    runner = PathBRunner(
        session_factory=SessionLocal,
        llm_extractor=mock_extractor,
        archival_insert_fn=fake_insert,
    )

    result: PathBRunResult = await runner.run_for_session(
        session_id=session_id, trigger_reason="session_closed"
    )
    assert result.episodes_scanned == 3
    assert result.chunks == 1  # 同 chunk
    assert result.facts_extracted == 1
    assert result.edges_inserted == 1
    assert mock_extractor.extract_facts.await_count == 1
    # 5 turn window 输入 = 3 turn (chunk 内 episode 数, < 5)
    call_kwargs = mock_extractor.extract_facts.await_args_list[0]
    turns = call_kwargs.kwargs.get("turns")
    assert turns is not None and len(turns) == 3
    # archival_memory_insert 收到 source_episode_id 是第 3 turn
    assert archival_calls[0]["episode_id"] == eids[2]
    assert archival_calls[0]["importance"] == 0.9


@pytest.mark.asyncio
async def test_path_b_extractor_failure_records_via_failure_matrix(
    pg_memory_fixture: dict[str, Any],
) -> None:
    """LLM 抛 → 走 failure_matrix.record_extraction_failure, episode.extracted_at 仍 NULL."""
    from app.memory.models import ChatMemoryEpisode

    engine = pg_memory_fixture["engine"]
    SessionLocal = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    user_id, session_id = _seed_user_session(pg_memory_fixture)
    base = datetime(2026, 5, 11, 10, 0, 0, tzinfo=UTC)
    eid = _make_episode(SessionLocal, user_id, session_id, 0, base, "我看好茅台")

    mock_extractor = MagicMock()
    mock_extractor.extract_facts = AsyncMock(side_effect=ValueError("invalid json"))
    mock_archival = AsyncMock()

    runner = PathBRunner(
        session_factory=SessionLocal,
        llm_extractor=mock_extractor,
        archival_insert_fn=mock_archival,
    )
    result = await runner.run_for_session(session_id=session_id, trigger_reason="session_closed")
    assert result.facts_extracted == 0
    assert result.failures == 1

    sess = SessionLocal()
    try:
        ep = sess.get(ChatMemoryEpisode, eid)
        assert ep is not None
        assert ep.extracted_at is None
        meta = dict(ep.extraction_metadata or {})
        assert meta.get("retry_count") == 1
    finally:
        sess.close()


@pytest.mark.asyncio
async def test_path_b_no_unextracted_returns_empty_result(
    pg_memory_fixture: dict[str, Any],
) -> None:
    """空 session (无 unextracted episode) → result.episodes_scanned=0."""
    engine = pg_memory_fixture["engine"]
    SessionLocal = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    _, session_id = _seed_user_session(pg_memory_fixture)

    mock_extractor = MagicMock()
    mock_extractor.extract_facts = AsyncMock()
    mock_archival = AsyncMock()

    runner = PathBRunner(
        session_factory=SessionLocal,
        llm_extractor=mock_extractor,
        archival_insert_fn=mock_archival,
    )
    result = await runner.run_for_session(session_id=session_id, trigger_reason="idle_30min")
    assert result.episodes_scanned == 0
    assert result.chunks == 0
    assert result.facts_extracted == 0
    mock_extractor.extract_facts.assert_not_called()
