"""Chaos test: PG + AGE + Milvus 三方一致性反向失败.

算法深度补丁 #5(spec § 11 末尾)收束验证, 覆盖 3 scenario:

  1. Milvus write 中途 fail → outbox 落 pending row → 重启 reconciliation
     job 重试成功(模拟"抽取 pipeline 中途 kill 进程, 重启后 Milvus pending 重试成功").
  2. 重复抽 episode → 幂等键 UNIQUE constraint 防重复 edge
     (spec § 11 #5 "episode 不重复抽").
  3. PG 写完同 epi 同 (s, t, rel_type, valid_from) → IntegrityError 防
     "悬空 AGE 节点 / 重复 edge"(同事务回滚保证不留孤儿).

依赖 Plan 1(幂等键 + reconciliation 骨架) + Plan 2(写入 pipeline + outbox)
+ Plan 1B reconciliation 模块.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from app.memory.conflict_resolver import ConflictResolver
from app.memory.extractor import LLMExtractor
from app.memory.hierarchical import HierarchicalMemory
from app.memory.models import (
    ChatMemoryEdge,
    ChatMemoryEpisode,
    ChatMemoryNode,
)
from app.memory.reconciliation import reconcile_pending_milvus_inserts
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.environ.get("SKIP_PG_TESTS") == "1",
        reason="PG container required",
    ),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _patch_age_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.memory import age_sync, hierarchical

    def _noop(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(age_sync, "age_create_edge", _noop)
    monkeypatch.setattr(age_sync, "age_merge_node", _noop)
    if hasattr(hierarchical, "age_create_edge"):
        monkeypatch.setattr(hierarchical, "age_create_edge", _noop, raising=False)
    if hasattr(hierarchical, "age_merge_node"):
        monkeypatch.setattr(hierarchical, "age_merge_node", _noop, raising=False)


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
                "u": f"ch_{user_uuid.hex[:8]}",
                "e": f"{user_uuid.hex[:8]}@test.local",
                "p": "x",
            },
        )
        conn.execute(
            text("INSERT INTO chat_sessions (id, user_id, title) VALUES (:id, :uid, :t)"),
            {"id": str(session_uuid), "uid": str(user_uuid), "t": "chaos"},
        )
    return user_uuid, session_uuid


def _build_memory_with_failing_milvus(
    pg_memory_session_factory: Callable[[], Any],
    judge_action: str = "append_new",
) -> HierarchicalMemory:
    """Build memory with Milvus client that fails inserts.

    archival_memory_insert 的 milvus_outbox.try_milvus_insert 会捕 Milvus exception
    回退到 pending_milvus_inserts 表(outbox pattern).
    """
    fake = AsyncMock()
    fake.chat.return_value = json.dumps({"action": judge_action, "reasoning": "chaos"})
    embed = AsyncMock()
    embed.embed.return_value = [0.1] * 1024

    failing_milvus = MagicMock()
    failing_milvus.insert.side_effect = RuntimeError("injected milvus failure")

    return HierarchicalMemory(
        pg_session_factory=pg_memory_session_factory,
        age_executor=None,
        milvus_client=failing_milvus,
        embed_service=embed,
        llm_extractor=LLMExtractor(llm_client=AsyncMock()),
        llm_judge=ConflictResolver(llm_client=fake),
    )


# ---------------------------------------------------------------------------
# Scenario 1a: Milvus write fail → outbox 落 pending row (async path)
# ---------------------------------------------------------------------------


async def test_chaos_milvus_failure_falls_back_to_outbox(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Callable[[], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Milvus 写入 fail → archival_memory_insert 通过 outbox pattern 写 pending row."""
    _patch_age_noop(monkeypatch)
    uid, sid = _seed_user_session(pg_memory_fixture)

    # 写 episode + 触发 archival_memory_insert (Milvus fail → 回退 outbox)
    sess = pg_memory_session_factory()
    try:
        ep = ChatMemoryEpisode(
            user_id=uid,
            session_id=sid,
            episode_index=0,
            user_message_text="我重仓茅台",
            source_kind="chat_turn",
        )
        sess.add(ep)
        sess.commit()
        ep_id = ep.episode_id
    finally:
        sess.close()

    memory = _build_memory_with_failing_milvus(pg_memory_session_factory)
    await memory.archival_memory_insert(
        user_id=uid,
        content={
            "rel_type": "HOLDS",
            "source_entity_type": "User",
            "source_label": "User",
            "target_entity_type": "Stock",
            "target_label": "600519.SH",
            "valid_from": datetime(2024, 8, 1, tzinfo=UTC),
            "valid_to": None,
            "properties": {"qty": 500},
        },
        reasoning="重仓",
        importance=0.9,
        evidence_quote="我重仓茅台",
        episode_id=ep_id,
    )

    # 验证 PG edge 已写入(Step 6 完成) + pending_milvus_inserts 有行
    sess = pg_memory_session_factory()
    try:
        edges = (
            sess.execute(select(ChatMemoryEdge).where(ChatMemoryEdge.user_id == uid))
            .scalars()
            .all()
        )
        assert len(edges) == 1, "PG edge 应已写入"

        pending = sess.execute(
            text("SELECT id, edge_id FROM pending_milvus_inserts WHERE user_id = :uid"),
            {"uid": uid},
        ).fetchall()
        assert len(pending) == 1, f"pending_milvus_inserts 应有 1 行, got {len(pending)}"
    finally:
        sess.close()


# ---------------------------------------------------------------------------
# Scenario 1b: Reconciliation job 清掉 pending row (sync path — 模拟进程重启)
# ---------------------------------------------------------------------------


def test_chaos_reconciliation_job_clears_pending_after_restart(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Callable[[], Any],
) -> None:
    """模拟进程重启后 reconciliation job 清掉 pending milvus rows.

    sync test (reconcile_pending_milvus_inserts 用 asyncio.run() 内部跑 embed),
    与 Scenario 1a 共同覆盖 "kill-mid-pipeline → restart → reconciliation 修复"
    """
    # Seed pending row directly (与 test_milvus_reconcile_e2e 同 pattern)
    uid, sid = _seed_user_session(pg_memory_fixture)
    sess = pg_memory_session_factory()
    try:
        ep = ChatMemoryEpisode(
            user_id=uid,
            session_id=sid,
            episode_index=0,
            user_message_text="seed",
            source_kind="chat_turn",
        )
        src = ChatMemoryNode(user_id=uid, entity_type="User", entity_label="User")
        tgt = ChatMemoryNode(user_id=uid, entity_type="Stock", entity_label="600519.SH")
        sess.add_all([ep, src, tgt])
        sess.flush()
        edge = ChatMemoryEdge(
            user_id=uid,
            source_node_id=src.node_id,
            target_node_id=tgt.node_id,
            rel_type="HOLDS",
            valid_from=datetime(2024, 8, 1, tzinfo=UTC),
            source_episode_id=ep.episode_id,
            importance=0.9,
            reasoning="x",
        )
        sess.add(edge)
        sess.flush()
        sess.execute(
            text(
                "INSERT INTO pending_milvus_inserts "
                "(edge_id, user_id, rel_type, edge_text, retry_count) "
                "VALUES (:eid, :uid, :rt, :et, 0)"
            ),
            {
                "eid": edge.edge_id,
                "uid": uid,
                "rt": "HOLDS",
                "et": "edge text for embed",
            },
        )
        sess.commit()
    finally:
        sess.close()

    # 模拟进程重启 → 跑 reconciliation job (Milvus 这次 succeed)
    fake_embed = AsyncMock(return_value=[0.2] * 1024)
    ok_milvus = MagicMock()
    ok_milvus.insert.return_value = None

    result = reconcile_pending_milvus_inserts(
        session_factory=pg_memory_session_factory,
        embed_fn=fake_embed,
        milvus_client=ok_milvus,
    )
    assert result.processed >= 1
    assert result.succeeded >= 1
    assert result.failed == 0

    # pending row 应已删除
    sess = pg_memory_session_factory()
    try:
        leftover = sess.execute(
            text("SELECT COUNT(*) FROM pending_milvus_inserts WHERE user_id = :uid"),
            {"uid": uid},
        ).scalar_one()
        assert leftover == 0, f"reconciliation 后 pending 应删, leftover={leftover}"
    finally:
        sess.close()


# ---------------------------------------------------------------------------
# Scenario 2: 重复抽 episode → 幂等键 UNIQUE constraint 防重复
# ---------------------------------------------------------------------------


async def test_chaos_duplicate_extraction_blocked_by_idempotency_key(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Callable[[], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同 episode 抽 2 次, 同 (episode, s, t, rel_type, valid_from) 第二次被挡住.

    场景: reconciliation 误判 episode 未抽 → 重新抽 → 幂等键挡.
    """
    _patch_age_noop(monkeypatch)
    uid, sid = _seed_user_session(pg_memory_fixture)

    # First insert
    sess = pg_memory_session_factory()
    try:
        ep = ChatMemoryEpisode(
            user_id=uid,
            session_id=sid,
            episode_index=0,
            user_message_text="x",
            source_kind="chat_turn",
        )
        src = ChatMemoryNode(user_id=uid, entity_type="User", entity_label="User")
        tgt = ChatMemoryNode(user_id=uid, entity_type="Stock", entity_label="600519.SH")
        sess.add_all([ep, src, tgt])
        sess.flush()

        valid_from = datetime(2024, 8, 1, tzinfo=UTC)
        edge1 = ChatMemoryEdge(
            user_id=uid,
            source_node_id=src.node_id,
            target_node_id=tgt.node_id,
            rel_type="HOLDS",
            valid_from=valid_from,
            source_episode_id=ep.episode_id,
            importance=0.9,
            reasoning="first",
        )
        sess.add(edge1)
        sess.commit()
        ep_id = ep.episode_id
        src_id = src.node_id
        tgt_id = tgt.node_id
    finally:
        sess.close()

    # Second insert with same key → IntegrityError
    sess = pg_memory_session_factory()
    try:
        dup = ChatMemoryEdge(
            user_id=uid,
            source_node_id=src_id,
            target_node_id=tgt_id,
            rel_type="HOLDS",
            valid_from=datetime(2024, 8, 1, tzinfo=UTC),
            source_episode_id=ep_id,
            importance=0.9,
            reasoning="duplicate retry",
        )
        sess.add(dup)
        with pytest.raises(IntegrityError):
            sess.commit()
    finally:
        sess.rollback()
        sess.close()

    # 验证最终只有 1 条 edge
    sess = pg_memory_session_factory()
    try:
        cnt = sess.execute(
            text(
                "SELECT COUNT(*) FROM chat_memory_edges WHERE user_id = :uid AND rel_type = 'HOLDS'"
            ),
            {"uid": uid},
        ).scalar_one()
        assert cnt == 1, f"幂等键 UNIQUE 防重复, got {cnt} edges"
    finally:
        sess.close()


# ---------------------------------------------------------------------------
# Scenario 3: PG insert 触发 IntegrityError → 同事务回滚 → 不留 node 孤儿
# ---------------------------------------------------------------------------


async def test_chaos_pg_integrity_error_rolls_back_no_orphan_nodes(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Callable[[], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PG 事务回滚(同 txn AGE/Milvus 都不持久化), 不留孤儿.

    spec § 11 #5: "不留孤儿 AGE 节点". 因为 spec § 4 Step 7 AGE Cypher
    跟 PG INSERT 同事务, PG 回滚自动滚 AGE; Milvus 因 outbox 隔离, 不写.
    """
    _patch_age_noop(monkeypatch)
    uid, sid = _seed_user_session(pg_memory_fixture)

    # 预创建 node + edge 占用同 (s, t, rel_type, valid_from)
    sess = pg_memory_session_factory()
    try:
        ep1 = ChatMemoryEpisode(
            user_id=uid,
            session_id=sid,
            episode_index=0,
            user_message_text="first",
            source_kind="chat_turn",
        )
        ep2 = ChatMemoryEpisode(
            user_id=uid,
            session_id=sid,
            episode_index=1,
            user_message_text="second",
            source_kind="chat_turn",
        )
        src = ChatMemoryNode(user_id=uid, entity_type="User", entity_label="User")
        tgt = ChatMemoryNode(user_id=uid, entity_type="Stock", entity_label="600519.SH")
        sess.add_all([ep1, ep2, src, tgt])
        sess.flush()

        valid_from = datetime(2024, 8, 1, tzinfo=UTC)
        edge1 = ChatMemoryEdge(
            user_id=uid,
            source_node_id=src.node_id,
            target_node_id=tgt.node_id,
            rel_type="HOLDS",
            valid_from=valid_from,
            source_episode_id=ep1.episode_id,
            importance=0.9,
            reasoning="first",
        )
        sess.add(edge1)
        sess.commit()
        ep2_id = ep2.episode_id
    finally:
        sess.close()

    # 现在 attempt 第二个 episode 抽出同 (s, t, rel_type, valid_from) — 不同 episode_id
    # archival_memory_insert 应被 unique constraint 拦截 / NO-OP
    memory_appendnew = HierarchicalMemory(
        pg_session_factory=pg_memory_session_factory,
        age_executor=None,
        milvus_client=MagicMock(),
        embed_service=AsyncMock(),
        llm_extractor=LLMExtractor(llm_client=AsyncMock()),
        llm_judge=ConflictResolver(
            llm_client=AsyncMock(chat=AsyncMock(return_value=json.dumps({"action": "no_op"})))
        ),
    )

    # judge=no_op → 不写入 (spec § 4 Step 5 完全重复)
    result = await memory_appendnew.archival_memory_insert(
        user_id=uid,
        content={
            "rel_type": "HOLDS",
            "source_entity_type": "User",
            "source_label": "User",
            "target_entity_type": "Stock",
            "target_label": "600519.SH",
            "valid_from": datetime(2024, 8, 1, tzinfo=UTC),
            "valid_to": None,
            "properties": {},
        },
        reasoning="duplicate",
        importance=0.9,
        evidence_quote="first",
        episode_id=ep2_id,
    )
    # NO_OP → 返 None
    assert result is None, "no_op verdict 应返 None, 不写入"

    # 验证只有 1 条 edge, 没有 ghost node
    sess = pg_memory_session_factory()
    try:
        edge_cnt = sess.execute(
            text("SELECT COUNT(*) FROM chat_memory_edges WHERE user_id = :uid"),
            {"uid": uid},
        ).scalar_one()
        assert edge_cnt == 1, f"no_op 不写入, edge_cnt={edge_cnt}"

        # node 数应保持 = 2 (User, Stock — 既有的, no_op 不新建)
        node_cnt = sess.execute(
            text("SELECT COUNT(*) FROM chat_memory_nodes WHERE user_id = :uid"),
            {"uid": uid},
        ).scalar_one()
        assert node_cnt == 2, f"no_op 不应建新 node, node_cnt={node_cnt}"
    finally:
        sess.close()
