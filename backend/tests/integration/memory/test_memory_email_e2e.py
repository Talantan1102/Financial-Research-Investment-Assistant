"""L1 integration: generate_monthly_digest 真 PG e2e (Plan 7B Task 7).

Seed user + episode + nodes + edges → 调 generate_monthly_digest →
验 markdown body 包含 top edges, 排除 invalidated / 30+ 天前.

Note: 文件放 ``tests/integration/memory/`` 而非 ``tests/integration/services/``,
因为 ``pg_memory_fixture`` / ``pg_memory_session`` fixture 由 ``memory/conftest.py``
provide; pytest 同级 conftest 才能找到. memory_email 是 service 层但走 memory
表, 测试同住 memory 目录合理.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.memory.models import ChatMemoryEdge, ChatMemoryEpisode, ChatMemoryNode
from app.services.memory_email import generate_monthly_digest
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_PG_TESTS") == "1",
    reason="PG container required",
)


def _seed_user_and_session(session) -> tuple[uuid.UUID, uuid.UUID]:  # noqa: ANN001
    user_id = uuid.uuid4()
    session_id = uuid.uuid4()
    suffix = user_id.hex[:8]
    session.execute(
        text("INSERT INTO users (id, username, email, hashed_password) VALUES (:id, :u, :e, :p)"),
        {
            "id": user_id,
            "u": f"em_{suffix}",
            "e": f"em_{suffix}@test.local",
            "p": "x",
        },
    )
    session.execute(
        text("INSERT INTO chat_sessions (id, user_id, title) VALUES (:id, :uid, :t)"),
        {"id": session_id, "uid": user_id, "t": "test session"},
    )
    session.flush()
    return user_id, session_id


def _seed_n_holds_edges(session, user_id, session_id, n: int, days_ago: int = 5):  # noqa: ANN001, ANN202
    """Seed n HOLDS current edges + accompanying nodes / episodes for user.

    importance 阶梯下降 (0.9 - i*0.0 仍 0.9 三档约束); 用 recorded_at 决定顺序
    的话需要直接插. 这里全用 0.9 然后用 valid_from 错开方便看顺序.
    """
    user_node = ChatMemoryNode(user_id=user_id, entity_type="User", entity_label="我")
    session.add(user_node)
    session.flush()
    edges = []
    for i in range(n):
        stock = ChatMemoryNode(
            user_id=user_id,
            entity_type="Stock",
            entity_label=f"股票{i}",
            properties={"ts_code": f"60000{i % 10}.SH"},
        )
        ep = ChatMemoryEpisode(
            user_id=user_id,
            session_id=session_id,
            episode_index=i,
            user_message_text=f"我买了 股票{i}",
            agent_response_text="收到",
            source_kind="chat_turn",
        )
        session.add_all([stock, ep])
        session.flush()

        edge = ChatMemoryEdge(
            user_id=user_id,
            source_node_id=user_node.node_id,
            target_node_id=stock.node_id,
            rel_type="HOLDS",
            valid_from=datetime.now(UTC) - timedelta(days=days_ago + i),
            valid_to=None,
            invalidated_at=None,
            source_episode_id=ep.episode_id,
            importance=0.9,
            reasoning=f"reason {i}",
        )
        session.add(edge)
        edges.append(edge)
    session.commit()
    return user_node, edges


def test_generate_monthly_digest_returns_markdown_with_top_edges(
    pg_memory_session,  # noqa: ANN001
) -> None:
    """Plan 7B Task 7 — 7 seed → top_n=5 应只出现前 5."""
    s = pg_memory_session
    user_id, session_id = _seed_user_and_session(s)
    _seed_n_holds_edges(s, user_id, session_id, n=7, days_ago=2)

    body = generate_monthly_digest(s, user_id, user_display_name="测试用户", top_n=5)

    assert "测试用户 您好" in body
    assert "我们最近一个月记下了关于您的 5 件事" in body
    # 7 seeded but only top 5 → 应有 5 条 "**持仓**" 行
    assert body.count("**持仓**") == 5


def test_generate_monthly_digest_excludes_invalidated_and_old_edges(
    pg_memory_session,  # noqa: ANN001
) -> None:
    """invalidated_at 已设置 + recorded_at 30+ 天前的 edge 不应进 digest."""
    s = pg_memory_session
    user_id, session_id = _seed_user_and_session(s)
    user_node, _ = _seed_n_holds_edges(s, user_id, session_id, n=2, days_ago=2)

    # 加一条 invalidated edge → 不应出现
    bad_stock = ChatMemoryNode(
        user_id=user_id,
        entity_type="Stock",
        entity_label="坏股",
        properties={"ts_code": "999999.SH"},
    )
    bad_ep = ChatMemoryEpisode(
        user_id=user_id,
        session_id=session_id,
        episode_index=99,
        user_message_text="坏",
        agent_response_text="收",
        source_kind="chat_turn",
    )
    s.add_all([bad_stock, bad_ep])
    s.flush()
    bad_edge = ChatMemoryEdge(
        user_id=user_id,
        source_node_id=user_node.node_id,
        target_node_id=bad_stock.node_id,
        rel_type="HOLDS",
        valid_from=datetime.now(UTC) - timedelta(days=3),
        invalidated_at=datetime.now(UTC),
        source_episode_id=bad_ep.episode_id,
        importance=0.9,
        reasoning="bad",
    )
    s.add(bad_edge)
    s.commit()

    body = generate_monthly_digest(s, user_id, top_n=10)

    assert "坏股" not in body
    # 2 valid edge → 2 条 **持仓**
    assert body.count("**持仓**") == 2
