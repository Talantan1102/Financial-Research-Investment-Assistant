"""L1 verify 幂等键 UNIQUE constraint(spec § 11 末尾 #5 算法深度补丁).

同 episode 重复抽出同 (s, t, rel_type, valid_from) → 第二次 insert raise IntegrityError.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import pytest
from app.memory.models import (
    ChatMemoryEdge,
    ChatMemoryEpisode,
    ChatMemoryNode,
)
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_PG_TESTS") == "1",
    reason="PG container required",
)


def _seed_user_and_session(session) -> tuple[uuid.UUID, uuid.UUID]:  # noqa: ANN001
    """Insert minimal users + chat_sessions row via raw SQL.

    NOTE: Use raw INSERT (only the columns we need + that exist in legacy
    test db schema) instead of ORM, because the test db has stale
    chat_sessions schema missing model columns like `message_count` /
    `last_msg_preview`. See e2e/test_pg_serve_path_e2e.py 注释 — full
    schema fix deferred to roadmap #3.5.
    """
    from sqlalchemy import text

    user_id = uuid.uuid4()
    session_id = uuid.uuid4()
    suffix = user_id.hex[:8]
    session.execute(
        text(
            "INSERT INTO users (id, username, email, hashed_password) "
            "VALUES (:id, :username, :email, :pwd)"
        ),
        {
            "id": user_id,
            "username": f"u_{suffix}",
            "email": f"u_{suffix}@test.local",
            "pwd": "x",
        },
    )
    session.execute(
        text("INSERT INTO chat_sessions (id, user_id, title) VALUES (:id, :user_id, :title)"),
        {"id": session_id, "user_id": user_id, "title": "t"},
    )
    session.flush()
    return user_id, session_id


def test_idempotency_key_blocks_duplicate_insert(pg_memory_session) -> None:  # noqa: ANN001
    """同 (episode, source_node, target_node, rel_type, valid_from) 第二次 insert raise."""
    s = pg_memory_session
    user_id, session_id = _seed_user_and_session(s)

    # episode + 2 nodes
    episode = ChatMemoryEpisode(
        user_id=user_id,
        session_id=session_id,
        episode_index=0,
        user_message_text="我买了茅台",
    )
    src = ChatMemoryNode(user_id=user_id, entity_type="User", entity_label="User")
    tgt = ChatMemoryNode(user_id=user_id, entity_type="Stock", entity_label="600519.SH")
    s.add_all([episode, src, tgt])
    s.flush()

    valid_from = datetime(2024, 8, 1, tzinfo=UTC)
    edge1 = ChatMemoryEdge(
        user_id=user_id,
        source_node_id=src.node_id,
        target_node_id=tgt.node_id,
        rel_type="HOLDS",
        valid_from=valid_from,
        source_episode_id=episode.episode_id,
        importance=0.9,
    )
    s.add(edge1)
    s.commit()

    # 重复 insert → IntegrityError
    edge2 = ChatMemoryEdge(
        user_id=user_id,
        source_node_id=src.node_id,
        target_node_id=tgt.node_id,
        rel_type="HOLDS",
        valid_from=valid_from,
        source_episode_id=episode.episode_id,
        importance=0.9,
    )
    s.add(edge2)
    with pytest.raises(IntegrityError):
        s.commit()


def test_idempotency_allows_different_valid_from(pg_memory_session) -> None:  # noqa: ANN001
    """同 (s, t, rel) 但不同 valid_from → 允许(场景 2 SOLD/HOLDS)."""
    s = pg_memory_session
    user_id, session_id = _seed_user_and_session(s)

    episode = ChatMemoryEpisode(
        user_id=user_id,
        session_id=session_id,
        episode_index=0,
        user_message_text="我清仓茅台",
    )
    src = ChatMemoryNode(user_id=user_id, entity_type="User", entity_label="User")
    tgt = ChatMemoryNode(user_id=user_id, entity_type="Stock", entity_label="600519.SH")
    s.add_all([episode, src, tgt])
    s.flush()

    edge1 = ChatMemoryEdge(
        user_id=user_id,
        source_node_id=src.node_id,
        target_node_id=tgt.node_id,
        rel_type="HOLDS",
        valid_from=datetime(2024, 8, 1, tzinfo=UTC),
        source_episode_id=episode.episode_id,
        importance=0.9,
    )
    edge2 = ChatMemoryEdge(
        user_id=user_id,
        source_node_id=src.node_id,
        target_node_id=tgt.node_id,
        rel_type="HOLDS",
        valid_from=datetime(2025, 1, 1, tzinfo=UTC),  # 不同 valid_from
        source_episode_id=episode.episode_id,
        importance=0.9,
    )
    s.add_all([edge1, edge2])
    s.commit()  # 不报错


def test_importance_check_constraint_rejects_continuous_value(  # noqa: ANN001
    pg_memory_session,
) -> None:
    """importance 三档 CHECK: 0.7(连续值) raise."""
    s = pg_memory_session
    user_id, session_id = _seed_user_and_session(s)

    episode = ChatMemoryEpisode(
        user_id=user_id,
        session_id=session_id,
        episode_index=0,
        user_message_text="x",
    )
    src = ChatMemoryNode(user_id=user_id, entity_type="User", entity_label="User")
    tgt = ChatMemoryNode(user_id=user_id, entity_type="Stock", entity_label="600519.SH")
    s.add_all([episode, src, tgt])
    s.flush()

    edge = ChatMemoryEdge(
        user_id=user_id,
        source_node_id=src.node_id,
        target_node_id=tgt.node_id,
        rel_type="HOLDS",
        valid_from=datetime(2024, 8, 1, tzinfo=UTC),
        source_episode_id=episode.episode_id,
        importance=0.7,  # 不是 0.9/0.5/0.2
    )
    s.add(edge)
    with pytest.raises(IntegrityError):
        s.commit()


def test_importance_three_tier_values_pass(pg_memory_session) -> None:  # noqa: ANN001
    """importance ∈ {0.9, 0.5, 0.2} 都 pass."""
    s = pg_memory_session
    user_id, session_id = _seed_user_and_session(s)

    for imp in (0.9, 0.5, 0.2):
        episode = ChatMemoryEpisode(
            user_id=user_id,
            session_id=session_id,
            episode_index=int(imp * 100),
            user_message_text="x",
        )
        src = ChatMemoryNode(user_id=user_id, entity_type="User", entity_label=f"User_{imp}")
        tgt = ChatMemoryNode(user_id=user_id, entity_type="Stock", entity_label=f"600519.SH_{imp}")
        s.add_all([episode, src, tgt])
        s.flush()
        edge = ChatMemoryEdge(
            user_id=user_id,
            source_node_id=src.node_id,
            target_node_id=tgt.node_id,
            rel_type="HOLDS",
            valid_from=datetime(2024, 8, 1, tzinfo=UTC),
            source_episode_id=episode.episode_id,
            importance=imp,
        )
        s.add(edge)
        s.commit()
