"""L1: persona populator e2e — 真 PG seed → 跑 → assert working_blocks."""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.memory.persona_populator import (
    PERSONA_BLOCK_NAME,
    PERSONA_MAX_TOKENS,
    populate_persona_on_session_start,
)
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_PG_TESTS") == "1",
    reason="PG container required",
)


def _seed_user_session(engine: Any, user_id: UUID, session_id: UUID) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, username, email, hashed_password, is_active) "
                "VALUES (:id, :u, :e, :p, true)"
            ),
            {
                "id": str(user_id),
                "u": f"pp_{user_id.hex[:8]}",
                "e": f"{user_id.hex[:8]}@test.local",
                "p": "x",
            },
        )
        conn.execute(
            text("INSERT INTO chat_sessions (id, user_id, title) VALUES (:id, :uid, :title)"),
            {"id": str(session_id), "uid": str(user_id), "title": "persona e2e"},
        )


def _seed_persona_edges(
    factory: Callable[[], Any],
    user_id: UUID,
    session_id: UUID,
) -> None:
    """Seed 4 类 edge: HOLDS / PREFERS / AVOIDS / WATCHES."""
    from app.memory.models import ChatMemoryEdge, ChatMemoryEpisode, ChatMemoryNode

    sess = factory()
    try:
        ep = ChatMemoryEpisode(
            user_id=user_id,
            session_id=session_id,
            episode_index=0,
            user_message_text="seed",
            source_kind="test_seed",
        )
        sess.add(ep)
        sess.flush()

        user_node = ChatMemoryNode(
            user_id=user_id, entity_type="User", entity_label="User", search_tokens="User"
        )
        sess.add(user_node)
        sess.flush()

        now = datetime.now(UTC)
        seeds: list[dict[str, Any]] = [
            {
                "label": "600519.SH",
                "entity_type": "Stock",
                "rel_type": "HOLDS",
                "imp": 0.9,
                "days_old": 10,
                "props": {"qty": 500, "thesis": "cash flow 稳"},
            },
            {
                "label": "DCF",
                "entity_type": "Strategy",
                "rel_type": "PREFERS",
                "imp": 0.5,
                "days_old": 20,
                "props": {"priority": 0.9},
            },
            {
                "label": "新能源 sector",
                "entity_type": "Sector",
                "rel_type": "AVOIDS",
                "imp": 0.5,
                "days_old": 30,
                "props": {"reason": "估值贵"},
            },
            {
                "label": "000858.SZ",
                "entity_type": "Stock",
                "rel_type": "WATCHES",
                "imp": 0.5,
                "days_old": 5,
                "props": {},
            },
        ]
        for s in seeds:
            target = ChatMemoryNode(
                user_id=user_id,
                entity_type=s["entity_type"],
                entity_label=s["label"],
                search_tokens=s["label"],
            )
            sess.add(target)
            sess.flush()
            edge = ChatMemoryEdge(
                user_id=user_id,
                source_node_id=user_node.node_id,
                target_node_id=target.node_id,
                rel_type=s["rel_type"],
                valid_from=now - timedelta(days=s["days_old"]),
                source_episode_id=ep.episode_id,
                importance=s["imp"],
                properties=s["props"],
                search_tokens=s["label"],
            )
            sess.add(edge)
        sess.commit()
    finally:
        sess.close()


def test_4_categories_in_persona_block(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Callable[[], Any],
) -> None:
    user_id = uuid4()
    session_id = uuid4()
    _seed_user_session(pg_memory_fixture["engine"], user_id, session_id)
    _seed_persona_edges(pg_memory_session_factory, user_id, session_id)

    populate_persona_on_session_start(pg_memory_session_factory, user_id=user_id)

    engine = pg_memory_fixture["engine"]
    with engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT content, token_count, max_tokens
                FROM chat_memory_working_blocks
                WHERE user_id = :uid AND block_name = :bn
                """
            ),
            {"uid": str(user_id), "bn": PERSONA_BLOCK_NAME},
        ).fetchone()
    assert row is not None
    content, tc, max_tc = row[0], row[1], row[2]
    assert "持仓" in content
    assert "600519.SH" in content
    assert "偏好" in content
    assert "DCF" in content
    assert "规避" in content
    assert "新能源" in content
    assert "关注" in content
    assert "000858.SZ" in content
    assert max_tc == PERSONA_MAX_TOKENS
    assert tc <= int(PERSONA_MAX_TOKENS * 1.5)  # buffer for char→token approximation


def test_empty_graph_yields_placeholder(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Callable[[], Any],
) -> None:
    """无 edges 用户 — populator 仍写一个 placeholder block."""
    user_id = uuid4()
    session_id = uuid4()
    _seed_user_session(pg_memory_fixture["engine"], user_id, session_id)

    populate_persona_on_session_start(pg_memory_session_factory, user_id=user_id)

    engine = pg_memory_fixture["engine"]
    with engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT content FROM chat_memory_working_blocks
                WHERE user_id = :uid AND block_name = :bn
                """
            ),
            {"uid": str(user_id), "bn": PERSONA_BLOCK_NAME},
        ).fetchone()
    assert row is not None
    assert "用户画像" in row[0]
    assert "暂无" in row[0]


def test_idempotent_overwrite(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Callable[[], Any],
) -> None:
    """二次跑 populate 应 UPSERT 而非新建第二行(uq_working_blocks_user_name)."""
    user_id = uuid4()
    session_id = uuid4()
    _seed_user_session(pg_memory_fixture["engine"], user_id, session_id)

    populate_persona_on_session_start(pg_memory_session_factory, user_id=user_id)
    populate_persona_on_session_start(pg_memory_session_factory, user_id=user_id)

    engine = pg_memory_fixture["engine"]
    with engine.begin() as conn:
        cnt = conn.execute(
            text(
                """
                SELECT COUNT(*) FROM chat_memory_working_blocks
                WHERE user_id = :uid AND block_name = :bn
                """
            ),
            {"uid": str(user_id), "bn": PERSONA_BLOCK_NAME},
        ).scalar_one()
    assert cnt == 1
