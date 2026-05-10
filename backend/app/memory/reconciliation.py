"""Reconciliation job 骨架 — scan inconsistent state.

spec ref: § 11 末尾 #5 三方一致性反向失败
contract ref: § 1 reconciliation.py 进程崩溃恢复 job 骨架

Plan 1B 范围(本):
- scan_inconsistent_state(user_id) → list[ReconciliationCase]
- 简单 case detection:
  - 'edge_exists_episode_unextracted': edge ref episode 但 episode.extracted_at IS NULL
    (Step 7 done, Step 8 崩) — Plan 5 weekly job 调 mark_episode_extracted 修
  - 'pending_milvus' placeholder — Plan 2/5 ship pending_milvus_inserts 表后接
- 不实施 retry / fix(Plan 5 weekly job 收束)

为啥 Plan 1B ship 入口骨架而不是放到 Plan 5:
  Plan 1A 已经 ship 了幂等键 UNIQUE constraint, Plan 1B 顺势 ship 这个 hook 让
  作品集叙事完整(算法深度补丁 #5 cover 全), Plan 5 只填实际 retry 逻辑.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReconciliationCase:
    """一条不一致 state 描述."""

    kind: str  # 'edge_exists_episode_unextracted' / 'pending_milvus' / ...
    user_id: UUID
    episode_id: UUID | None
    edge_id: UUID | None
    description: str


async def scan_inconsistent_state(
    user_id: Any,
    pg_session_factory: Any,
) -> list[ReconciliationCase]:
    """扫描 user_id 的不一致 state.

    Plan 1B 检测的 case:
    1. edge_exists_episode_unextracted: edge ref episode 但 episode.extracted_at IS NULL
       (Step 7 done, Step 8 崩 — Plan 5 修)

    Plan 1B 不检测但留 hook(Plan 2/5 ship 后接):
    2. pending_milvus: pending_milvus_inserts 表存在 row(Plan 2 ship 此表)
    3. age_pg_drift: AGE 图节点 vs PG nodes 数量不一致(Plan 5 weekly chaos test 收束)
    """
    from app.memory.models import ChatMemoryEdge, ChatMemoryEpisode

    cases: list[ReconciliationCase] = []

    sess = pg_session_factory()
    try:
        # case 1: edge 存在但 episode extracted_at IS NULL
        rows = (
            sess.query(ChatMemoryEdge, ChatMemoryEpisode)
            .join(
                ChatMemoryEpisode,
                ChatMemoryEdge.source_episode_id == ChatMemoryEpisode.episode_id,
            )
            .filter(
                ChatMemoryEdge.user_id == user_id,
                ChatMemoryEpisode.extracted_at.is_(None),
                ChatMemoryEpisode.source_kind != "cold_start_seed",
                # cold_start_seed 走特殊路径 extracted_at 已设置, 但即便不设置也 OK
            )
            .all()
        )
        for edge, ep in rows:
            cases.append(
                ReconciliationCase(
                    kind="edge_exists_episode_unextracted",
                    user_id=user_id,
                    episode_id=ep.episode_id,
                    edge_id=edge.edge_id,
                    description=(
                        f"edge {edge.edge_id} ref episode {ep.episode_id}, "
                        f"but episode.extracted_at is NULL (Step 8 likely crashed)"
                    ),
                )
            )

        if cases:
            logger.warning(
                "reconciliation: detected %d inconsistent cases for user %s",
                len(cases),
                user_id,
            )

        # case 2 placeholder: pending_milvus_inserts 表(Plan 2 ship)
        # try:
        #     from app.memory.models import PendingMilvusInsert  # Plan 2 ship
        #     pending = sess.query(PendingMilvusInsert).filter_by(user_id=user_id).all()
        #     for p in pending:
        #         cases.append(ReconciliationCase(kind="pending_milvus", ...))
        # except ImportError:
        #     pass

        return cases
    finally:
        sess.close()
