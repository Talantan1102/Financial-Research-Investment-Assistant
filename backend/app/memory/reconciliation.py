"""Reconciliation jobs — scan inconsistent state + Milvus pending retry.

spec ref:
- § 11 末尾 #5 三方一致性反向失败 (Plan 1B 骨架)
- § 4 末尾失败矩阵 行 5 (Plan 2B Milvus pending retry job)

contract ref: § 1 reconciliation.py 进程崩溃恢复 job 骨架

Plan 1B 范围:
- scan_inconsistent_state(user_id) → list[ReconciliationCase]

Plan 2B 范围 (本 Task 6 加):
- reconcile_pending_milvus_inserts(session_factory, embed_fn, milvus_client)
  → ReconcileResult: 扫 pending_milvus_inserts → retry embed + insert →
  成功删 / 失败 retry_count++ / max-3 alert.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)


# ===== Plan 2B Milvus reconcile constants =====

MAX_RECONCILE_RETRIES = 3
RECONCILE_BATCH_LIMIT = 200


@dataclass
class ReconcileResult:
    """Milvus pending reconciliation 跑一轮的结果."""

    processed: int
    succeeded: int
    failed: int
    alerted: int


EmbedFn = Callable[[str], Awaitable[list[float]]]


def reconcile_pending_milvus_inserts(
    session_factory: sessionmaker[Session] | Callable[[], Session],
    embed_fn: EmbedFn,
    milvus_client: Any,
) -> ReconcileResult:
    """扫 pending_milvus_inserts 行, retry embed + Milvus insert.

    成功 → DELETE 行
    失败 → retry_count + 1, last_error / last_attempt_at 更新
    retry_count >= MAX_RECONCILE_RETRIES → log error('max_reconcile_retries_exceeded'),
      行保留(不删 不 retry, 留作 audit)

    Plan 2A migration (`pending_milvus_inserts`) 列名 (per Plan 2A SQL):
    - id (BIGSERIAL PK)
    - edge_id (UUID FK chat_memory_edges)
    - edge_text (TEXT)
    - user_id / rel_type
    - retry_count / last_error / created_at / last_attempt_at
    """
    sess = session_factory()
    processed = 0
    succeeded = 0
    failed = 0
    alerted = 0
    try:
        rows = sess.execute(
            text(
                """SELECT id, edge_id, edge_text, retry_count
                   FROM pending_milvus_inserts
                   ORDER BY created_at ASC
                   LIMIT :lim"""
            ),
            {"lim": RECONCILE_BATCH_LIMIT},
        ).fetchall()
        for row in rows:
            processed += 1
            pending_id = row[0]
            edge_id = row[1]
            edge_text = row[2] or f"edge:{edge_id}"
            retry_count = int(row[3] or 0)
            if retry_count >= MAX_RECONCILE_RETRIES:
                logger.error(
                    "max_reconcile_retries_exceeded edge_id=%s retry_count=%d — manual triage",
                    edge_id,
                    retry_count,
                )
                alerted += 1
                continue
            try:
                embedding: list[float] = asyncio.run(embed_fn(edge_text))  # type: ignore[arg-type]
                milvus_client.insert(
                    collection_name="chat_memory_edge_embeddings",
                    data=[
                        {
                            "edge_id": str(edge_id),
                            "embedding": embedding,
                        }
                    ],
                )
                sess.execute(
                    text("DELETE FROM pending_milvus_inserts WHERE id=:pid"),
                    {"pid": pending_id},
                )
                sess.commit()
                succeeded += 1
            except Exception as exc:  # noqa: BLE001  intentional accumulator
                failed += 1
                sess.rollback()
                sess.execute(
                    text(
                        """UPDATE pending_milvus_inserts
                           SET retry_count = retry_count + 1,
                               last_error = :err,
                               last_attempt_at = :ts
                           WHERE id = :pid"""
                    ),
                    {
                        "pid": pending_id,
                        "err": str(exc)[:500],
                        "ts": datetime.now(tz=UTC),
                    },
                )
                sess.commit()
                logger.warning("reconcile failed for edge %s: %s", edge_id, exc)
        return ReconcileResult(
            processed=processed, succeeded=succeeded, failed=failed, alerted=alerted
        )
    finally:
        sess.close()


# ===== Plan 1B scan inconsistent state (untouched skeleton) =====


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
