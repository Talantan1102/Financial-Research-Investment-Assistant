"""L1 — Path B 端到端跨轮抽取 (real PG + mock LLM).

Spec § 11 末尾 #4 跨轮抽取核心断言:
1. 3 turn dialogue → 5 turn window 输入 LLM → 完整 HOLDS edge
2. 单 turn fact 不退化 (EXPRESSED_VIEW)
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
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
                "u": f"pbe_{user_uuid.hex[:8]}",
                "e": f"{user_uuid.hex[:8]}@test.local",
                "p": "x",
            },
        )
        conn.execute(
            text("INSERT INTO chat_sessions (id, user_id, title) VALUES (:id, :uid, :t)"),
            {"id": str(session_uuid), "uid": str(user_uuid), "t": "pbe"},
        )
    return user_uuid, session_uuid


def _seed_three_turn(SessionLocal: Any, session_id: UUID, user_id: UUID) -> list[UUID]:
    from app.memory.models import ChatMemoryEpisode

    base = datetime(2026, 5, 11, 10, 0, 0, tzinfo=UTC)
    sess = SessionLocal()
    eids: list[UUID] = []
    try:
        for i, (msg, ts_offset) in enumerate(
            [
                ("我刚买了股票", 0),
                ("买什么", 2),
                ("茅台 600519, 500 股", 4),
            ]
        ):
            ep = ChatMemoryEpisode(
                episode_id=uuid4(),
                user_id=user_id,
                session_id=session_id,
                episode_index=i,
                user_message_text=msg,
                agent_response_text="",
                source_kind="chat_turn",
                created_at=base + timedelta(minutes=ts_offset),
            )
            sess.add(ep)
            sess.flush()
            eids.append(ep.episode_id)  # type: ignore[arg-type]
        sess.commit()
        return eids
    finally:
        sess.close()


@pytest.mark.asyncio
async def test_cross_turn_fact_extraction_full_path(
    pg_memory_fixture: dict[str, Any],
) -> None:
    """3 turn dialogue → 5 turn window 输入 LLM → 抽出完整 HOLDS edge."""
    engine = pg_memory_fixture["engine"]
    SessionLocal = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    user_id, session_id = _seed_user_session(pg_memory_fixture)
    eids = _seed_three_turn(SessionLocal, session_id, user_id)

    captured_turns: list[list[dict[str, Any]]] = []

    async def fake_extract(
        turns: list[dict[str, Any]],
        session_id: UUID,
        episode_ids: list[UUID],
    ) -> dict[str, Any]:
        captured_turns.append(turns)
        return {
            "entities": [
                {"entity_type": "Stock", "entity_label": "600519.SH", "properties": {}},
            ],
            "edges": [
                {
                    "rel_type": "HOLDS",
                    "source_label": "User",
                    "target_label": "600519.SH",
                    "valid_from": datetime.now(tz=UTC).isoformat(),
                    "valid_to": None,
                    "importance": 0.9,
                    "reasoning": "user explicitly bought 500 shares",
                    "evidence_quote": "茅台 600519, 500 股",
                    "properties": {"qty": 500},
                    "source_episode_id": str(episode_ids[-1]),
                }
            ],
        }

    mock_extractor = MagicMock()
    mock_extractor.extract_facts = AsyncMock(side_effect=fake_extract)

    captured_inserts: list[dict[str, Any]] = []

    async def fake_insert(**kwargs: Any) -> Any:
        captured_inserts.append(kwargs)
        return MagicMock(edge_id=uuid4())

    runner = PathBRunner(
        session_factory=SessionLocal,
        llm_extractor=mock_extractor,
        archival_insert_fn=fake_insert,
    )
    result = await runner.run_for_session(session_id=session_id, trigger_reason="session_closed")

    assert result.episodes_scanned == 3
    assert result.chunks == 1  # 3 turn 同 chunk(< 5min 间隔)
    assert result.facts_extracted == 1
    assert result.edges_inserted == 1
    # LLM 收到完整 3 turn (window=5, 3 < 5 全返回)
    assert len(captured_turns[0]) == 3
    # archival_memory_insert 收到 fact source_episode_id == 第 3 turn
    assert captured_inserts[0]["importance"] == 0.9
    assert captured_inserts[0]["evidence_quote"] == "茅台 600519, 500 股"
    assert captured_inserts[0]["episode_id"] == eids[2]
    content = captured_inserts[0]["content"]
    assert content.get("rel_type") == "HOLDS"
    assert content.get("target_label") == "600519.SH"
    assert content.get("properties", {}).get("qty") == 500


@pytest.mark.asyncio
async def test_single_turn_fact_does_not_regress(
    pg_memory_fixture: dict[str, Any],
) -> None:
    """单 turn 也能抽出 EXPRESSED_VIEW (不因跨轮逻辑伤单 turn)."""
    from app.memory.models import ChatMemoryEpisode

    engine = pg_memory_fixture["engine"]
    SessionLocal = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    user_id, session_id = _seed_user_session(pg_memory_fixture)
    sess = SessionLocal()
    try:
        sess.add(
            ChatMemoryEpisode(
                episode_id=uuid4(),
                user_id=user_id,
                session_id=session_id,
                episode_index=0,
                user_message_text="我看好茅台护城河",
                agent_response_text="",
                source_kind="chat_turn",
                created_at=datetime.now(tz=UTC),
            )
        )
        sess.commit()
    finally:
        sess.close()

    mock_extractor = MagicMock()
    mock_extractor.extract_facts = AsyncMock(
        return_value={
            "entities": [
                {"entity_type": "Stock", "entity_label": "600519.SH", "properties": {}},
            ],
            "edges": [
                {
                    "rel_type": "EXPRESSED_VIEW",
                    "source_label": "User",
                    "target_label": "600519.SH",
                    "valid_from": datetime.now(tz=UTC).isoformat(),
                    "valid_to": None,
                    "importance": 0.5,
                    "reasoning": "positive view on moat",
                    "evidence_quote": "我看好茅台护城河",
                    "properties": {},
                }
            ],
        }
    )
    mock_archival = AsyncMock(return_value=MagicMock(edge_id=uuid4()))
    runner = PathBRunner(
        session_factory=SessionLocal,
        llm_extractor=mock_extractor,
        archival_insert_fn=mock_archival,
    )
    result = await runner.run_for_session(session_id=session_id, trigger_reason="idle_30min")
    assert result.facts_extracted == 1
    assert result.edges_inserted == 1
    assert result.episodes_scanned == 1
    assert result.chunks == 1
