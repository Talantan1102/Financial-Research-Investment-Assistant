"""Milvus outbox pattern for write pipeline (spec § 4 Step 7).

策略:
1. Try inline: embed via qwen v3, insert to Milvus collection 'chat_memory_edge_embeddings'.
2. 异常时: write pending_milvus_inserts row, do NOT rollback PG.
3. Plan 2B Celery job 每 5 分钟扫表 retry.

算法深度补丁 #5 三方一致性: 主 PG 写入 source-of-truth, Milvus eventual consistent.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from typing import Any, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.memory.models import ChatMemoryEdge

_logger = logging.getLogger(__name__)


def build_edge_embed_text(
    *,
    rel_type: str,
    source_entity_type: str,
    source_label: str,
    target_entity_type: str,
    target_label: str,
    reasoning: str,
    properties: dict[str, Any],
) -> str:
    """spec § 2 Milvus collection edge embed text 模板.

    格式: "{rel_type} {src_type} {src_label} → {tgt_type} {tgt_label} reasoning='{reasoning}' props={json}"
    """
    return (
        f"{rel_type} {source_entity_type} {source_label} → "
        f"{target_entity_type} {target_label} "
        f"reasoning='{reasoning}' props={json.dumps(properties, ensure_ascii=False)}"
    )


def enqueue_milvus_insert(
    session: Session,
    *,
    edge_id: UUID,
    edge_text: str,
    user_id: UUID,
    rel_type: str,
    last_error: str,
) -> None:
    """写 pending_milvus_inserts 一行.

    UNIQUE(edge_id) 防重: 重复 enqueue 时 ON CONFLICT 更新 last_error / retry_count
    保留 (Plan 2B Celery 扫表时按 retry_count 决定 alert).
    """
    session.execute(
        text(
            """
            INSERT INTO pending_milvus_inserts
                (edge_id, edge_text, user_id, rel_type, retry_count, last_error)
            VALUES (:eid, :etext, :uid, :rt, 0, :err)
            ON CONFLICT (edge_id) DO UPDATE
                SET last_error = EXCLUDED.last_error,
                    last_attempt_at = now()
            """
        ),
        {
            "eid": str(edge_id),
            "etext": edge_text,
            "uid": str(user_id),
            "rt": rel_type,
            "err": last_error[:500],  # truncate to keep row small
        },
    )


async def _maybe_await(value: Any) -> Any:
    """Embed/Milvus 客户端可能是 sync 或 async; 统一兼容."""
    if inspect.isawaitable(value):
        return await value
    return value


async def try_milvus_insert(
    *,
    session: Session,
    milvus_client: Any,
    embed_service: Any,
    edge: ChatMemoryEdge,
    edge_text: str,
) -> bool:
    """Try inline qwen embed + Milvus insert.

    Returns True on success, False if any step failed (and outbox row written).

    DOES NOT raise — failure is fully absorbed via outbox so PG transaction
    can commit (spec § 4 失败处理矩阵: Milvus 失败 → 写 pending_milvus_inserts).
    """
    edge_id_uuid = cast(UUID, edge.edge_id)
    user_id_uuid = cast(UUID, edge.user_id)
    rel_type_str = cast(str, edge.rel_type)

    try:
        embed_call = embed_service.embed(edge_text)
        embedding = await _maybe_await(embed_call)
    except Exception as exc:  # noqa: BLE001  intentional outbox absorb
        _logger.warning(
            "milvus outbox: embed failed for edge_id=%s: %s",
            edge_id_uuid,
            exc,
        )
        enqueue_milvus_insert(
            session=session,
            edge_id=edge_id_uuid,
            edge_text=edge_text,
            user_id=user_id_uuid,
            rel_type=rel_type_str,
            last_error=f"embed failed: {exc}",
        )
        return False

    try:
        # pymilvus collection.insert 接受 list of dict
        insert_call = milvus_client.insert(
            collection_name="chat_memory_edge_embeddings",
            data=[
                {
                    "edge_id": str(edge_id_uuid),
                    "user_id": str(user_id_uuid),
                    "embedding": embedding,
                    "rel_type": rel_type_str,
                }
            ],
        )
        # pymilvus is sync but allow async clients in tests
        if asyncio.iscoroutine(insert_call):
            await insert_call
    except Exception as exc:  # noqa: BLE001  intentional outbox absorb
        _logger.warning(
            "milvus outbox: insert failed for edge_id=%s: %s",
            edge_id_uuid,
            exc,
        )
        enqueue_milvus_insert(
            session=session,
            edge_id=edge_id_uuid,
            edge_text=edge_text,
            user_id=user_id_uuid,
            rel_type=rel_type_str,
            last_error=f"milvus insert failed: {exc}",
        )
        return False

    return True
