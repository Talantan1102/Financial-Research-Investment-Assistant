"""MEMORY.md 等价的只读 DB 索引投影。

索引只暴露“有哪些记忆类别/多少条”，不包含用户事实正文、实体标签或对话原文。
具体内容继续以 PG 为真相源，并通过 ``memory_search`` 按需渐进读取；这里不创建、
同步或伪造任何 MEMORY.md 文件。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func

from app.memory.models import ChatMemoryEdge, ChatMemoryWorkingBlock


def build_memory_index_projection(session_factory: Any, user_id: UUID) -> dict[str, Any]:
    """从当前 PG 快照构建无正文索引。"""
    session = session_factory()
    try:
        blocks = (
            session.query(
                ChatMemoryWorkingBlock.block_name,
                ChatMemoryWorkingBlock.token_count,
            )
            .filter(ChatMemoryWorkingBlock.user_id == user_id)
            .order_by(ChatMemoryWorkingBlock.block_name.asc())
            .all()
        )
        relation_rows = (
            session.query(ChatMemoryEdge.rel_type, func.count(ChatMemoryEdge.edge_id))
            .filter(
                ChatMemoryEdge.user_id == user_id,
                ChatMemoryEdge.invalidated_at.is_(None),
                ChatMemoryEdge.valid_to.is_(None),
            )
            .group_by(ChatMemoryEdge.rel_type)
            .order_by(ChatMemoryEdge.rel_type.asc())
            .all()
        )
        latest = (
            session.query(func.max(ChatMemoryEdge.recorded_at))
            .filter(
                ChatMemoryEdge.user_id == user_id,
                ChatMemoryEdge.invalidated_at.is_(None),
                ChatMemoryEdge.valid_to.is_(None),
            )
            .scalar()
        )
        relations = {str(rel): int(count) for rel, count in relation_rows}
        return {
            "working_blocks": [
                {"name": str(name), "token_count": int(tokens or 0)} for name, tokens in blocks
            ],
            "archival": {
                "total": sum(relations.values()),
                "relations": relations,
                "latest_recorded_at": latest.isoformat() if latest is not None else None,
            },
        }
    finally:
        session.close()


def render_memory_index(projection: dict[str, Any]) -> str:
    """把 DB 投影渲染成稳定、紧凑的 MEMORY.md 等价索引摘要。"""
    blocks = projection.get("working_blocks") or []
    archival = projection.get("archival") or {}
    relations = archival.get("relations") or {}

    block_text = (
        ", ".join(
            f"{block.get('name', 'unknown')} ({int(block.get('token_count') or 0)} tokens)"
            for block in blocks
        )
        or "无"
    )
    relation_text = (
        ", ".join(f"{name}: {int(count)}" for name, count in sorted(relations.items())) or "无"
    )
    latest = archival.get("latest_recorded_at") or "无"

    return (
        "## MEMORY.md（数据库投影索引）\n"
        f"- 核心块: {block_text}\n"
        f"- 长期记忆: 共 {int(archival.get('total') or 0)} 条; 分类 {relation_text}\n"
        f"- 最近记录时间: {latest}\n"
        "- 具体记忆请按需调用 memory_search；本索引不包含记忆正文。"
    )


__all__ = ["build_memory_index_projection", "render_memory_index"]
