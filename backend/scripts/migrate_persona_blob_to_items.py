"""一次性 backfill: 老 persona blob → chat_memory_persona_items (Plan Task 6).

调用时机：app_main lifespan startup 时检测一次。
跑过的标记位记在每个 user 的 working_block.token_count 字段（向后兼容方案），
而是用 "if 该 user 已有 persona_items 则 skip" 做幂等判断。
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID, uuid4

from app.memory.models import ChatMemoryPersonaItem, ChatMemoryWorkingBlock
from app.memory.persona_items_md import ItemDraft, parse_markdown_to_drafts
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def parse_existing_blob_for_user(existing_blob: str | None) -> list[ItemDraft]:
    """老 blob 无 H2 → drafts 全部 source='agent'（parse_markdown_to_drafts 默认行为）."""
    if not existing_blob:
        return []
    return parse_markdown_to_drafts(existing_blob)


def migrate_user_persona(*, session: Session, user_id: UUID) -> dict[str, Any]:
    """迁移单用户 — 幂等。"""

    existing_count = session.query(ChatMemoryPersonaItem).filter_by(user_id=user_id).count()
    if existing_count > 0:
        return {"status": "skipped", "reason": "items already present"}

    block = (
        session.query(ChatMemoryWorkingBlock)
        .filter_by(user_id=user_id, block_name="persona")
        .first()
    )
    if block is None:
        return {"status": "noop", "reason": "no persona block"}

    drafts = parse_existing_blob_for_user(existing_blob=str(block.content))
    if not drafts:
        return {"status": "noop", "reason": "empty blob"}

    for d in drafts:
        item = ChatMemoryPersonaItem(
            item_id=uuid4(),
            user_id=user_id,
            source=d.source,
            text=d.text,
            position=d.position,
        )
        session.add(item)

    session.commit()
    return {"status": "migrated", "count": len(drafts)}


def migrate_all(session_factory: Any) -> dict[str, int]:
    """遍历所有有 persona block 的 user 跑一次."""
    stats: dict[str, int] = {"migrated": 0, "skipped": 0, "noop": 0, "errors": 0}
    session = session_factory()
    try:
        users = (
            session.query(ChatMemoryWorkingBlock.user_id)
            .filter_by(block_name="persona")
            .distinct()
            .all()
        )
        user_ids = [row[0] for row in users]
    finally:
        session.close()

    for uid in user_ids:
        per_user_session = session_factory()
        try:
            result = migrate_user_persona(session=per_user_session, user_id=uid)
            key = result["status"]
            stats[key] = stats.get(key, 0) + 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("persona migration failed user=%s: %s", uid, exc)
            stats["errors"] += 1
        finally:
            per_user_session.close()

    return stats
