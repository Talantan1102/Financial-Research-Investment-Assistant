"""一次性 backfill: 老 persona blob → chat_memory_persona_items (Plan Task 6).

调用时机：app_main lifespan startup 时检测一次。
**不记**跑过的标记位（如 working_block.token_count 字段），而是用 "if 该 user 已有
persona_items 则 skip" 做幂等判断 — schema 简单 + 反映实际状态而非可能漂移的 flag。

## 已知限制 (v1.0 接受, scale 前修复)

- **多 worker race**: count() == 0 → INSERT 是 TOCTOU; `uvicorn --workers N` /
  k8s replicas N 启动时, N 个 worker 同时观测 count == 0, 同时 insert 会双倍 row.
  当前单实例 dev 不撞; 多 worker 前需加 PG advisory lock (`pg_try_advisory_xact_lock`
  hashed by user_id) 或 UNIQUE(user_id, source, position) + IntegrityError 兜底.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.memory.models import ChatMemoryPersonaItem, ChatMemoryWorkingBlock
from app.memory.persona_items_md import ItemDraft, parse_markdown_to_drafts

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
        except Exception:
            logger.exception("persona migration failed user=%s", uid)
            stats["errors"] += 1
        finally:
            per_user_session.close()

    return stats
