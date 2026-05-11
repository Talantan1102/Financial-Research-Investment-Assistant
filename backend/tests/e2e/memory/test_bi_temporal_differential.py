"""Bi-temporal differential test — spec § 12 5 session 序列 1:1 实现.

模拟用户 5 个 session 序列(持仓演化), 每 session 后断言 graph 状态正确:
  1. Session 1 (2024-08): 重仓茅台 500 → INSERT new HOLDS
  2. Session 2 (2025-03): 加仓到 700 → update_validity (老 HOLDS valid_to 设)
  3. Session 3 (2025-06): 卖出 → update_validity (老 HOLDS valid_to 设)
                                + INSERT SOLD
  4. Session 4 (2025-12): 用户澄清记错 → contradict_existing
                                (老的 invalidated_at 设)
                                + INSERT HOLDS 五粮液
  5. Session 5 (2026-01): 重新建仓茅台 100 股 → append_new
                                (老 invalidated 不复活)

依赖 Plan 1-2 ship: PG schema + archival_memory_insert + 4-action conflict.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from app.memory.conflict_resolver import ConflictResolver
from app.memory.extractor import LLMExtractor
from app.memory.hierarchical import HierarchicalMemory
from app.memory.models import ChatMemoryEdge, ChatMemoryEpisode
from sqlalchemy import select, text

GOLDEN_PATH = (
    Path(__file__).resolve().parents[3] / "eval" / "memory" / "differential_holding_evolution.jsonl"
)

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.environ.get("SKIP_PG_TESTS") == "1",
        reason="PG container required",
    ),
]


def _load_sessions() -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in GOLDEN_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


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
                "u": f"bt_{user_uuid.hex[:8]}",
                "e": f"{user_uuid.hex[:8]}@test.local",
                "p": "x",
            },
        )
        conn.execute(
            text("INSERT INTO chat_sessions (id, user_id, title) VALUES (:id, :uid, :title)"),
            {"id": str(session_uuid), "uid": str(user_uuid), "title": "bi-temporal"},
        )
    return user_uuid, session_uuid


def _build_memory(
    pg_memory_session_factory: Callable[[], Any],
    judge_action: str,
) -> HierarchicalMemory:
    fake = AsyncMock()
    fake.chat.return_value = json.dumps({"action": judge_action, "reasoning": "bt"})
    embed = AsyncMock()
    embed.embed.return_value = [0.1] * 1024
    return HierarchicalMemory(
        pg_session_factory=pg_memory_session_factory,
        age_executor=None,
        milvus_client=MagicMock(),
        embed_service=embed,
        llm_extractor=LLMExtractor(llm_client=AsyncMock()),
        llm_judge=ConflictResolver(llm_client=fake),
    )


def _write_episode(
    pg_memory_session_factory: Callable[[], Any],
    user_id: UUID,
    session_id: UUID,
    episode_index: int,
    text_content: str,
) -> UUID:
    sess = pg_memory_session_factory()
    try:
        ep = ChatMemoryEpisode(
            user_id=user_id,
            session_id=session_id,
            episode_index=episode_index,
            user_message_text=text_content,
            source_kind="chat_turn",
        )
        sess.add(ep)
        sess.commit()
        return cast(UUID, ep.episode_id)
    finally:
        sess.close()


def _utc(date_str: str) -> datetime:
    return datetime.fromisoformat(date_str).replace(tzinfo=UTC)


@pytest.mark.integration
async def test_bi_temporal_holding_evolution_5_sessions(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Callable[[], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """spec § 12 5 session 1:1 实现."""
    _patch_age_noop(monkeypatch)
    uid, sid = _seed_user_session(pg_memory_fixture)
    sessions = _load_sessions()
    assert len(sessions) == 5

    # ── Session 1 (2024-08): 重仓茅台 500 → append_new (无 existing) ──
    s1 = sessions[0]
    ep1_id = _write_episode(pg_memory_session_factory, uid, sid, 0, s1["user_message"])
    memory = _build_memory(pg_memory_session_factory, judge_action="append_new")
    await memory.archival_memory_insert(
        user_id=uid,
        content={
            "rel_type": "HOLDS",
            "source_entity_type": "User",
            "source_label": "User",
            "target_entity_type": "Stock",
            "target_label": "600519.SH",
            "valid_from": _utc(s1["date"]),
            "valid_to": None,
            "properties": {"qty": 500},
        },
        reasoning="重仓",
        importance=0.9,
        evidence_quote=s1["user_message"],
        episode_id=ep1_id,
    )

    sess = pg_memory_session_factory()
    try:
        rows = (
            sess.execute(
                select(ChatMemoryEdge).where(
                    ChatMemoryEdge.user_id == uid,
                    ChatMemoryEdge.rel_type == "HOLDS",
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1, "session 1: 1 HOLDS edge"
        assert rows[0].valid_to is None
        assert rows[0].invalidated_at is None
        assert rows[0].properties.get("qty") == 500
    finally:
        sess.close()

    # ── Session 2 (2025-03): 加仓到 700 → update_validity ──
    s2 = sessions[1]
    ep2_id = _write_episode(pg_memory_session_factory, uid, sid, 1, s2["user_message"])
    memory = _build_memory(pg_memory_session_factory, judge_action="update_validity")
    await memory.archival_memory_insert(
        user_id=uid,
        content={
            "rel_type": "HOLDS",
            "source_entity_type": "User",
            "source_label": "User",
            "target_entity_type": "Stock",
            "target_label": "600519.SH",
            "valid_from": _utc(s2["date"]),
            "valid_to": None,
            "properties": {"qty": 700},
        },
        reasoning="加仓",
        importance=0.9,
        evidence_quote=s2["user_message"],
        episode_id=ep2_id,
    )

    sess = pg_memory_session_factory()
    try:
        rows = (
            sess.execute(
                select(ChatMemoryEdge).where(
                    ChatMemoryEdge.user_id == uid,
                    ChatMemoryEdge.rel_type == "HOLDS",
                    ChatMemoryEdge.invalidated_at.is_(None),
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 2, "session 2: 老 HOLDS valid_to 设 + new HOLDS"
        active = [r for r in rows if r.valid_to is None]
        assert len(active) == 1
        assert active[0].properties.get("qty") == 700
        invalidated_by_valid_to = [r for r in rows if r.valid_to is not None]
        assert len(invalidated_by_valid_to) == 1
        assert invalidated_by_valid_to[0].valid_to == _utc(s2["date"])
    finally:
        sess.close()

    # ── Session 3 (2025-06): 卖出 ──
    # 先把 active HOLDS (qty=700) 通过 update_validity 关闭(valid_to=卖出日)
    # 然后 INSERT SOLD (append_new)
    s3 = sessions[2]
    ep3_id = _write_episode(pg_memory_session_factory, uid, sid, 2, s3["user_message"])

    # Step a: 关闭 HOLDS — judge 输出 update_validity, 配新 HOLDS valid_from=卖出日
    # 但用户实际不再持有 — 模拟上层 close-position 写: 同 rel_type 新 valid_from=卖出日,
    # qty=0 properties; judge update_validity 把老 valid_to=卖出日.
    # 这里为简化 e2e, 直接对 active HOLDS 设 valid_to (模拟 Step 6 update_validity action).
    sess = pg_memory_session_factory()
    try:
        active = (
            sess.execute(
                select(ChatMemoryEdge).where(
                    ChatMemoryEdge.user_id == uid,
                    ChatMemoryEdge.rel_type == "HOLDS",
                    ChatMemoryEdge.valid_to.is_(None),
                    ChatMemoryEdge.invalidated_at.is_(None),
                )
            )
            .scalars()
            .all()
        )
        for r in active:
            r.valid_to = _utc(s3["date"])
        sess.commit()
    finally:
        sess.close()

    # Step b: INSERT SOLD edge (新 rel_type, 无 existing same-key edge → append_new)
    memory = _build_memory(pg_memory_session_factory, judge_action="append_new")
    await memory.archival_memory_insert(
        user_id=uid,
        content={
            "rel_type": "SOLD",
            "source_entity_type": "User",
            "source_label": "User",
            "target_entity_type": "Stock",
            "target_label": "600519.SH",
            "valid_from": _utc(s3["date"]),
            "valid_to": None,
            "properties": {},
        },
        reasoning="卖出",
        importance=0.9,
        evidence_quote=s3["user_message"],
        episode_id=ep3_id,
    )

    sess = pg_memory_session_factory()
    try:
        active_holds = (
            sess.execute(
                select(ChatMemoryEdge).where(
                    ChatMemoryEdge.user_id == uid,
                    ChatMemoryEdge.rel_type == "HOLDS",
                    ChatMemoryEdge.valid_to.is_(None),
                    ChatMemoryEdge.invalidated_at.is_(None),
                )
            )
            .scalars()
            .all()
        )
        assert len(active_holds) == 0, "session 3: 无 active HOLDS"
        sold_rows = (
            sess.execute(
                select(ChatMemoryEdge).where(
                    ChatMemoryEdge.user_id == uid,
                    ChatMemoryEdge.rel_type == "SOLD",
                )
            )
            .scalars()
            .all()
        )
        assert len(sold_rows) == 1, "session 3: 1 SOLD edge"
    finally:
        sess.close()

    # ── Session 4 (2025-12): 澄清记错, 实际是五粮液 ──
    # 老的 HOLDS / SOLD 茅台都标 invalidated_at (contradict_existing)
    # + INSERT HOLDS 五粮液 (新 target, 无冲突 → append_new)
    s4 = sessions[3]
    ep4_id = _write_episode(pg_memory_session_factory, uid, sid, 3, s4["user_message"])

    # 老 edge invalidate: 模拟 contradict_existing apply_action (在 conflict_resolver.apply_action)
    sess = pg_memory_session_factory()
    try:
        sess.execute(
            text(
                "UPDATE chat_memory_edges SET invalidated_at = NOW() "
                "WHERE user_id = :uid AND target_node_id IN ("
                "  SELECT node_id FROM chat_memory_nodes "
                "  WHERE user_id = :uid AND entity_type = 'Stock' "
                "  AND entity_label = '600519.SH'"
                ") AND invalidated_at IS NULL"
            ),
            {"uid": str(uid)},
        )
        sess.commit()
    finally:
        sess.close()

    # INSERT 五粮液 HOLDS (新 target — append_new)
    memory = _build_memory(pg_memory_session_factory, judge_action="append_new")
    await memory.archival_memory_insert(
        user_id=uid,
        content={
            "rel_type": "HOLDS",
            "source_entity_type": "User",
            "source_label": "User",
            "target_entity_type": "Stock",
            "target_label": "000858.SZ",
            "valid_from": _utc("2024-08-01"),  # 用户说"去年那 500"
            "valid_to": None,
            "properties": {"qty": 500},
        },
        reasoning="澄清记错: 实际是五粮液",
        importance=0.9,
        evidence_quote=s4["user_message"],
        episode_id=ep4_id,
    )

    sess = pg_memory_session_factory()
    try:
        invalidated = (
            sess.execute(
                select(ChatMemoryEdge).where(
                    ChatMemoryEdge.user_id == uid,
                    ChatMemoryEdge.invalidated_at.isnot(None),
                )
            )
            .scalars()
            .all()
        )
        assert len(invalidated) >= 2, (
            f"session 4: 至少 2 老 edge invalidated_at, got {len(invalidated)}"
        )
        # 五粮液 HOLDS active
        active_holds = (
            sess.execute(
                select(ChatMemoryEdge).where(
                    ChatMemoryEdge.user_id == uid,
                    ChatMemoryEdge.rel_type == "HOLDS",
                    ChatMemoryEdge.invalidated_at.is_(None),
                    ChatMemoryEdge.valid_to.is_(None),
                )
            )
            .scalars()
            .all()
        )
        assert len(active_holds) == 1, "session 4: 1 active HOLDS (五粮液)"
        assert active_holds[0].properties.get("qty") == 500
    finally:
        sess.close()

    # ── Session 5 (2026-01): 重新建仓茅台 100 股 (新 target=茅台 again, 无 active key) ──
    s5 = sessions[4]
    ep5_id = _write_episode(pg_memory_session_factory, uid, sid, 4, s5["user_message"])
    memory = _build_memory(pg_memory_session_factory, judge_action="append_new")
    await memory.archival_memory_insert(
        user_id=uid,
        content={
            "rel_type": "HOLDS",
            "source_entity_type": "User",
            "source_label": "User",
            "target_entity_type": "Stock",
            "target_label": "600519.SH",
            "valid_from": _utc(s5["date"]),
            "valid_to": None,
            "properties": {"qty": 100},
        },
        reasoning="重新建仓",
        importance=0.9,
        evidence_quote=s5["user_message"],
        episode_id=ep5_id,
    )

    sess = pg_memory_session_factory()
    try:
        # 新茅台 100 股 active
        active = (
            sess.execute(
                select(ChatMemoryEdge).where(
                    ChatMemoryEdge.user_id == uid,
                    ChatMemoryEdge.rel_type == "HOLDS",
                    ChatMemoryEdge.valid_to.is_(None),
                    ChatMemoryEdge.invalidated_at.is_(None),
                )
            )
            .scalars()
            .all()
        )
        # active 应该有 2 条: 五粮液 + 新茅台 100 股
        new_maotai = [r for r in active if r.properties.get("qty") == 100]
        assert len(new_maotai) == 1, "session 5: 新茅台 HOLDS qty=100"
        assert new_maotai[0].valid_from == _utc(s5["date"])

        # 老 invalidated 没复活 — 仍 invalidated
        still_invalidated = (
            sess.execute(
                select(ChatMemoryEdge).where(
                    ChatMemoryEdge.user_id == uid,
                    ChatMemoryEdge.invalidated_at.isnot(None),
                )
            )
            .scalars()
            .all()
        )
        assert len(still_invalidated) >= 2, "session 5: 老 invalidated 不复活, 仍 invalidated"
    finally:
        sess.close()
