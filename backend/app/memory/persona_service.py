"""PersonaService — Tier 1 persona block 的 atomic 持久化层.

spec § 3 / § 7.x：暴露 list/add/update/delete + apply_agent_append/replace + render_to_markdown。

CRUD 由 UI REST endpoint 调；apply_agent_* 由 HierarchicalMemory.core_memory_*
转译；render_to_markdown 由 _sync_to_working_block 写回 ChatMemoryWorkingBlock
保 ChatPlanner / prefix cache 兼容。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Literal, TypedDict
from uuid import UUID, uuid4

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.memory.models import ChatMemoryPersonaItem, ChatMemoryWorkingBlock
from app.memory.persona_items_md import render_items_to_markdown

logger = logging.getLogger(__name__)

_TEXT_MAX = 500
TargetSection = Literal["user", "agent"]


class PersonaListResult(TypedDict):
    user_declared: list[ChatMemoryPersonaItem]
    agent_inferred: list[ChatMemoryPersonaItem]


class PersonaService:
    def __init__(self, pg_session_factory: Callable[[], Session]) -> None:
        self._session_factory = pg_session_factory

    # ----- CRUD -----

    def list_items(self, *, user_id: UUID) -> PersonaListResult:
        session = self._session_factory()
        try:
            user_items = (
                session.query(ChatMemoryPersonaItem)
                .filter_by(user_id=user_id, source="user")
                .order_by(ChatMemoryPersonaItem.position.asc())
                .all()
            )
            agent_items = (
                session.query(ChatMemoryPersonaItem)
                .filter_by(user_id=user_id, source="agent")
                .order_by(ChatMemoryPersonaItem.position.asc())
                .all()
            )
            return {"user_declared": list(user_items), "agent_inferred": list(agent_items)}
        finally:
            session.close()

    def add_item(
        self,
        *,
        user_id: UUID,
        text: str,
        target_section: TargetSection,
    ) -> ChatMemoryPersonaItem:
        normalized = self._validate_text(text)
        session = self._session_factory()
        try:
            position = self._next_position(session, user_id=user_id, source=target_section)
            item = ChatMemoryPersonaItem(
                item_id=uuid4(),
                user_id=user_id,
                source=target_section,
                text=normalized,
                position=position,
            )
            session.add(item)
            session.commit()
            session.refresh(item)
            session.expunge(item)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
        self._sync_to_working_block(session=None, user_id=user_id)
        return item

    def update_item(self, *, user_id: UUID, item_id: UUID, text: str) -> ChatMemoryPersonaItem:
        normalized = self._validate_text(text)
        session = self._session_factory()
        try:
            item = (
                session.query(ChatMemoryPersonaItem)
                .filter_by(item_id=item_id, user_id=user_id)
                .first()
            )
            if item is None:
                raise LookupError(f"persona item {item_id} not found for user {user_id}")

            item.text = normalized  # type: ignore[assignment]

            if item.source == "agent":
                # spec 決策 3: 改 agent 区条 → 升级到 user 区，position 改为 user max+1
                item.source = "user"  # type: ignore[assignment]
                item.position = self._next_position(session, user_id=user_id, source="user")  # type: ignore[assignment]

            session.commit()
            session.refresh(item)
            session.expunge(item)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
        self._sync_to_working_block(session=None, user_id=user_id)
        return item

    def delete_item(self, *, user_id: UUID, item_id: UUID) -> None:
        session = self._session_factory()
        try:
            item = (
                session.query(ChatMemoryPersonaItem)
                .filter_by(item_id=item_id, user_id=user_id)
                .first()
            )
            if item is None:
                raise LookupError(f"persona item {item_id} not found for user {user_id}")
            session.delete(item)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
        self._sync_to_working_block(session=None, user_id=user_id)

    # ----- agent write API (HierarchicalMemory.core_memory_* 转译) -----

    def apply_agent_append(self, *, user_id: UUID, content: str) -> list[ChatMemoryPersonaItem]:
        """append 多行 content 为 agent 区 items.

        prefix `- ` / `* ` 自动去除；空行跳过；每行一 item。
        """

        normalized_lines = self._normalize_agent_lines(content)
        if not normalized_lines:
            return []

        session = self._session_factory()
        try:
            base_pos = self._next_position(session, user_id=user_id, source="agent")
            new_items: list[ChatMemoryPersonaItem] = []
            for offset, text in enumerate(normalized_lines):
                item = ChatMemoryPersonaItem(
                    item_id=uuid4(),
                    user_id=user_id,
                    source="agent",
                    text=text,
                    position=base_pos + offset,
                )
                session.add(item)
                new_items.append(item)
            session.commit()
            for item in new_items:
                session.refresh(item)
                session.expunge(item)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
        self._sync_to_working_block(session=None, user_id=user_id)
        return new_items

    def apply_agent_replace(
        self, *, user_id: UUID, old_content: str, new_content: str
    ) -> list[ChatMemoryPersonaItem]:
        """agent 区 match → 改 text；未匹配（含 user 区命中）→ fallback append.

        双轨保护：filter_by(source='agent') 永远不会扫到 user 区行 — 即使 text
        完全一致也不会被改。
        """

        old_normalized = old_content.strip()
        new_normalized = new_content.strip()
        if not new_normalized:
            logger.warning("apply_agent_replace: new_content empty after strip, no-op")
            return []

        matched_target: ChatMemoryPersonaItem | None = None
        session = self._session_factory()
        try:
            candidates = (
                session.query(ChatMemoryPersonaItem)
                .filter_by(user_id=user_id, source="agent")
                .order_by(ChatMemoryPersonaItem.position.asc())
                .all()
            )
            matched = [c for c in candidates if c.text.strip() == old_normalized]
            if matched:
                target = matched[0]
                target.text = new_normalized  # type: ignore[assignment]
                session.commit()
                session.refresh(target)
                session.expunge(target)
                matched_target = target
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

        if matched_target is not None:
            self._sync_to_working_block(session=None, user_id=user_id)
            return [matched_target]

        # fallback: 没命中 → append 一条新 agent item（含命中 user 区也走这）
        logger.warning(
            "apply_agent_replace: old_content not matched in agent section "
            "(user_id=%s, old_len=%d) — falling back to append",
            user_id,
            len(old_normalized),
        )
        return self.apply_agent_append(user_id=user_id, content=new_normalized)

    @staticmethod
    def _normalize_agent_lines(content: str) -> list[str]:
        out: list[str] = []
        for raw in content.splitlines():
            line = raw.strip()
            if not line:
                continue
            if line.startswith("- ") or line.startswith("* "):
                line = line[2:].strip()
            if line:
                out.append(line)
        return out

    # ----- render / sync -----

    def render_to_markdown(self, *, user_id: UUID) -> str:
        result = self.list_items(user_id=user_id)
        return render_items_to_markdown(
            user_items=[i.text for i in result["user_declared"]],  # type: ignore[misc]
            agent_items=[i.text for i in result["agent_inferred"]],  # type: ignore[misc]
        )

    # ----- internal helpers -----

    @staticmethod
    def _validate_text(text: str) -> str:
        normalized = text.strip()
        if not normalized:
            raise ValueError("persona item text empty")
        if len(normalized) > _TEXT_MAX:
            raise ValueError(f"persona item text too long (max {_TEXT_MAX})")
        return normalized

    @staticmethod
    def _next_position(session: Session, *, user_id: UUID, source: TargetSection) -> int:
        """Return next available position (max + 1) for given user + source section."""
        max_pos = (
            session.query(ChatMemoryPersonaItem)
            .filter_by(user_id=user_id, source=source)
            .with_entities(func.max(ChatMemoryPersonaItem.position))
            .scalar()
        )
        if max_pos is None:
            return 0
        return int(max_pos) + 1

    def _sync_to_working_block(self, *, session: Session | None, user_id: UUID) -> None:
        """渲染 items → markdown → 写回 ChatMemoryWorkingBlock.persona.content.

        保 ChatPlanner Phase 1 render_persona_markdown 路径不变；下次 session
        起手 frozen snapshot 时自动拿最新值。

        # 已知 debt (v1 接受, scale 前修复):
        # - 并发 insert race: working_blocks unique(user_id, block_name); 当前
        #   read-then-write 模式两个并发 op 可能同 observe None 同时 add. 当前
        #   dogfood 阶段 UI 单 tab + agent 单线程触发, 概率极低. Task 17 wire
        #   agent 写后概率上升, scale 前换 pg_insert(...).on_conflict_do_update.
        # - token_count 写 0 是 placeholder; 真实 token count 计算待集成 qwen
        #   tokenizer (跟 kb chunking embedding 一致), v1 不阻塞 ChatPlanner 路径.
        """

        markdown = self.render_to_markdown(user_id=user_id)
        own_session = session is None
        sess = session or self._session_factory()
        try:
            block = (
                sess.query(ChatMemoryWorkingBlock)
                .filter_by(user_id=user_id, block_name="persona")
                .first()
            )
            if block is None:
                block = ChatMemoryWorkingBlock(
                    user_id=user_id,
                    block_name="persona",
                    content=markdown,
                    max_tokens=500,
                    token_count=0,
                )
                sess.add(block)
            else:
                block.content = markdown  # type: ignore[assignment]
            sess.commit()
        except Exception:
            sess.rollback()
            raise
        finally:
            if own_session:
                sess.close()
