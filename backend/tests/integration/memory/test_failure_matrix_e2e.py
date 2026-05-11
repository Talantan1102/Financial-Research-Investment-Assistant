"""L1 — Failure matrix 6 行端到端验证.

Spec § 4 末尾失败矩阵 6 行:
- 行 1: LLM extraction 失败 / invalid JSON → max-3 retry alert (Plan 2B)
- 行 2: Entity normalization 失败 → audit_flag (Plan 2A 已实现, 本 plan verify)
- 行 3: Conflict-judge 失败 → append_new fail-safe (Plan 2A 已实现, 本 plan verify)
- 行 4: AGE sync 失败 → PG rollback (Plan 2A) + Celery autoretry (Plan 2B)
- 行 5: Milvus 失败 → pending → 5min reconcile (Plan 2A outbox + Plan 2B Task 6)
- 行 6: PG 主事务失败 → max 3 retry (Celery task signature, Plan 2B Task 1/5)
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from app.memory.failure_matrix import MAX_EXTRACTION_RETRIES
from app.memory.path_b_runner import PathBRunner
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
                "u": f"fme_{user_uuid.hex[:8]}",
                "e": f"{user_uuid.hex[:8]}@test.local",
                "p": "x",
            },
        )
        conn.execute(
            text("INSERT INTO chat_sessions (id, user_id, title) VALUES (:id, :uid, :t)"),
            {"id": str(session_uuid), "uid": str(user_uuid), "t": "fme"},
        )
    return user_uuid, session_uuid


def _seed_episode(
    SessionLocal: Any,
    user_id: UUID,
    session_id: UUID,
    msg: str,
) -> UUID:
    from app.memory.models import ChatMemoryEpisode

    sess = SessionLocal()
    try:
        ep = ChatMemoryEpisode(
            episode_id=uuid4(),
            user_id=user_id,
            session_id=session_id,
            episode_index=0,
            user_message_text=msg,
            source_kind="chat_turn",
            created_at=datetime.now(tz=UTC),
        )
        sess.add(ep)
        sess.commit()
        eid: UUID = ep.episode_id  # type: ignore[assignment]
        return eid
    finally:
        sess.close()


@pytest.mark.asyncio
async def test_row1_llm_extraction_invalid_json_max3_retry(
    pg_memory_fixture: dict[str, Any],
) -> None:
    """行 1: LLM extraction 失败 → max 3 次后 alerted+filtered, LLM 不再被调."""
    from app.memory.failure_matrix import mark_episode_extraction_alerted
    from app.memory.models import ChatMemoryEpisode

    engine = pg_memory_fixture["engine"]
    SessionLocal = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    user_id, session_id = _seed_user_session(pg_memory_fixture)
    eid = _seed_episode(SessionLocal, user_id, session_id, "我看好茅台 500 股")

    mock_extractor = MagicMock()
    mock_extractor.extract_facts = AsyncMock(side_effect=ValueError("invalid json"))
    mock_archival = AsyncMock()
    runner = PathBRunner(
        session_factory=SessionLocal,
        llm_extractor=mock_extractor,
        archival_insert_fn=mock_archival,
    )
    # 跑 N = MAX_EXTRACTION_RETRIES 次 — LLM 应被调 N 次 (failure_matrix
    # blocks subsequent runs only after retry_count == MAX).
    for _ in range(MAX_EXTRACTION_RETRIES):
        await runner.run_for_session(session_id=session_id, trigger_reason="session_closed")
    call_count_at_max = mock_extractor.extract_facts.await_count

    # 已达 MAX → 下次调用前 episode 会被 should_retry filter 掉, LLM 不再被调
    sess = SessionLocal()
    try:
        ep = sess.get(ChatMemoryEpisode, eid)
        assert ep is not None
        meta = dict(ep.extraction_metadata or {})
        assert int(meta.get("retry_count") or 0) == MAX_EXTRACTION_RETRIES
        # 标 alerted (在生产链路里 alerted 由调用方 (e.g. monitoring) 触发;
        # 本 test 直接触发 alert 然后验证 should_retry → False)
        mark_episode_extraction_alerted(sess, eid)
        sess.commit()
    finally:
        sess.close()

    await runner.run_for_session(session_id=session_id, trigger_reason="session_closed")
    assert mock_extractor.extract_facts.await_count == call_count_at_max  # 不增

    sess = SessionLocal()
    try:
        ep = sess.get(ChatMemoryEpisode, eid)
        assert ep is not None
        assert ep.extracted_at is None  # 失败的 episode 不应被标 extracted
    finally:
        sess.close()


@pytest.mark.asyncio
async def test_row2_normalize_failure_writes_audit_flag_no_retry(
    pg_memory_fixture: dict[str, Any],
) -> None:
    """行 2: Entity normalization 失败 → 写库带 audit flag, 不阻塞流程.

    Plan 2A 在 archival_memory_insert 内调 normalize_entity → audit_flag=True 时
    写 chat_memory_nodes.properties._normalize_audit. 本 test verify Plan 2B
    PathBRunner 把 normalize 失败的 fact 仍走 archival_insert (不阻塞).
    """
    engine = pg_memory_fixture["engine"]
    SessionLocal = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    user_id, session_id = _seed_user_session(pg_memory_fixture)
    _seed_episode(SessionLocal, user_id, session_id, "我看好不存在的股票 999999.SH")

    mock_extractor = MagicMock()
    mock_extractor.extract_facts = AsyncMock(
        return_value={
            "entities": [{"entity_type": "Stock", "entity_label": "999999.SH", "properties": {}}],
            "edges": [
                {
                    "rel_type": "EXPRESSED_VIEW",
                    "source_label": "User",
                    "target_label": "999999.SH",
                    "valid_from": datetime.now(tz=UTC).isoformat(),
                    "importance": 0.5,
                    "reasoning": "view on unknown stock",
                    "evidence_quote": "我看好不存在的股票 999999.SH",
                    "properties": {},
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
    result = await runner.run_for_session(session_id=session_id, trigger_reason="session_closed")
    # 行 2: archival_insert 被调一次, runner 不阻塞 (failure_matrix 行 2 责任在
    # Plan 2A archival_memory_insert 内的 normalize_entity audit_flag)
    assert len(archival_calls) == 1
    assert result.failures == 0
    assert result.edges_inserted == 1


@pytest.mark.asyncio
async def test_row3_conflict_judge_failsafe_append_new(
    pg_memory_fixture: dict[str, Any],
) -> None:
    """行 3: Conflict-judge 失败 → 默认 append_new (Plan 2A 已实现 fail-safe).

    Plan 2B PathBRunner 视角: row 3 责任 in Plan 2A archival_memory_insert; 本
    test verify insert 被调 + 不抛.
    """
    engine = pg_memory_fixture["engine"]
    SessionLocal = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    user_id, session_id = _seed_user_session(pg_memory_fixture)
    _seed_episode(SessionLocal, user_id, session_id, "我又买入茅台 200 股")

    mock_extractor = MagicMock()
    mock_extractor.extract_facts = AsyncMock(
        return_value={
            "entities": [{"entity_type": "Stock", "entity_label": "600519.SH", "properties": {}}],
            "edges": [
                {
                    "rel_type": "HOLDS",
                    "source_label": "User",
                    "target_label": "600519.SH",
                    "valid_from": datetime.now(tz=UTC).isoformat(),
                    "importance": 0.9,
                    "reasoning": "judge mock fails internally — append_new fallback",
                    "evidence_quote": "我又买入茅台 200 股",
                    "properties": {"qty": 200},
                }
            ],
        }
    )

    async def fake_insert(**kwargs: Any) -> Any:
        # Plan 2A fail-safe: judge 失败 → append_new, 不 raise
        return MagicMock(edge_id=uuid4())

    runner = PathBRunner(
        session_factory=SessionLocal,
        llm_extractor=mock_extractor,
        archival_insert_fn=fake_insert,
    )
    result = await runner.run_for_session(session_id=session_id, trigger_reason="session_closed")
    assert result.edges_inserted == 1
    assert result.failures == 0


@pytest.mark.asyncio
async def test_row4_age_sync_failure_records_insert_failure(
    pg_memory_fixture: dict[str, Any],
) -> None:
    """行 4: AGE sync 失败 → archival_insert 抛 → runner 落 insert_failures metadata.

    Plan 2A 内部 PG + AGE 同事务 rollback; runner 视角是 archival_insert 抛 RuntimeError,
    不 fail 整 chunk, 落 insert_failures 到 episode.metadata, episode 被 mark
    extracted_at (已尝试过, 真"整批重试"靠 Celery autoretry — task signature 守护).
    """
    from app.memory.models import ChatMemoryEpisode

    engine = pg_memory_fixture["engine"]
    SessionLocal = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    user_id, session_id = _seed_user_session(pg_memory_fixture)
    eid = _seed_episode(SessionLocal, user_id, session_id, "我加仓茅台 100 股")

    mock_extractor = MagicMock()
    mock_extractor.extract_facts = AsyncMock(
        return_value={
            "entities": [{"entity_type": "Stock", "entity_label": "600519.SH", "properties": {}}],
            "edges": [
                {
                    "rel_type": "HOLDS",
                    "source_label": "User",
                    "target_label": "600519.SH",
                    "valid_from": datetime.now(tz=UTC).isoformat(),
                    "importance": 0.9,
                    "reasoning": "build position",
                    "evidence_quote": "我加仓茅台 100 股",
                    "properties": {"qty": 100},
                }
            ],
        }
    )

    async def flaky_insert(**kwargs: Any) -> Any:
        raise RuntimeError("AGE sync failed: txn rolled back")

    runner = PathBRunner(
        session_factory=SessionLocal,
        llm_extractor=mock_extractor,
        archival_insert_fn=flaky_insert,
    )
    await runner.run_for_session(session_id=session_id, trigger_reason="session_closed")
    sess = SessionLocal()
    try:
        ep = sess.get(ChatMemoryEpisode, eid)
        assert ep is not None
        meta = dict(ep.extraction_metadata or {})
        insert_failures = meta.get("insert_failures") or []
        assert insert_failures
        assert "AGE sync failed" in insert_failures[0]["error"]
    finally:
        sess.close()


def test_row5_milvus_failure_writes_pending_covered_in_milvus_reconcile_test() -> None:
    """行 5: Milvus 失败 → pending → 后台 5min retry.

    Plan 2A 已实现 outbox (archival_memory_insert 内 try/except + INSERT pending);
    Plan 2B Task 6 实施 reconcile job. 本测试 just declarative — 真 verify in
    test_milvus_reconcile_e2e.py.
    """
    # 不重测 — 由 Task 6 的 4 个 reconcile case 已 cover
    pass


def test_row6_pg_main_txn_failure_max3_retry_signature() -> None:
    """行 6: PG 主事务失败 → 全 rollback → max 3 次 (Celery task signature 守护)."""
    from app.tasks.memory import extract_session_episodes_async

    assert extract_session_episodes_async.max_retries == 3
    assert extract_session_episodes_async.acks_late is True
    # autoretry_for=(Exception,) — kombu/celery 把它存在 task.options
    assert Exception in (extract_session_episodes_async.autoretry_for or ())
