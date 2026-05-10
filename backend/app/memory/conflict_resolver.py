"""ConflictResolver — spec § 4 Step 5 + Step 6 Apply Action SQL.

Step 5: LLM judge 4-action + fail-safe.
Step 6: Apply action with bi-temporal correctness (Task 4 加 apply_action method).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.memory.models import ChatMemoryEdge

_logger = logging.getLogger(__name__)


class ConflictAction(StrEnum):
    """spec § 4 Step 5 4-action."""

    UPDATE_VALIDITY = "update_validity"  # 现实演化, existing.valid_to=new.valid_from + INSERT new
    CONTRADICT_EXISTING = (
        "contradict_existing"  # 系统记错, existing.invalidated_at=now() + INSERT new
    )
    APPEND_NEW = "append_new"  # 独立共存, INSERT new only
    NO_OP = "no_op"  # 完全重复, skip


class ConflictVerdict(BaseModel):
    action: ConflictAction
    reasoning: str = Field(default="")


_JUDGE_SYSTEM_PROMPT = """\
你是金融 chat agent 的 memory conflict resolver.

给定一条新事实和若干现有事实, 判定如何融合.

四种 action:
- update_validity: 新事实表明现实演化(买了→卖了 / 看法改变)
   → existing.valid_to = new.valid_from, INSERT new edge
- contradict_existing: 新事实表明系统记错(用户澄清纠正)
   → existing.invalidated_at = now(), INSERT new edge
- append_new: 不矛盾, 独立存在
   → INSERT new edge
- no_op: 完全重复, 跳过
   → 不做任何写入

输出 JSON: {"action": "<one of four>", "reasoning": "<短解释>"}

**只输出 JSON, 不输出其他文字.**
"""

_JUDGE_USER_PROMPT_TEMPLATE = """\
# 新事实
{new_edge_summary}

# 现有事实(最多 5 条, 按 valid_from 倒序)
{existing_edges_block}
"""


class ConflictResolver:
    """spec § 4 Step 5 LLM-judge + fail-safe."""

    def __init__(
        self,
        llm_client: Any,
        model: str = "claude-haiku-4.5",
        max_tokens: int = 256,
    ) -> None:
        self._llm = llm_client
        self._model = model
        self._max_tokens = max_tokens

    async def judge(
        self,
        new_edge_summary: str,
        existing_edges_summary: list[str],
    ) -> ConflictVerdict:
        """Returns ConflictVerdict. Fail-safe to APPEND_NEW on any error.

        spec § 4 Step 5 fail-safe semantics: 保守, 不丢信息.
        """
        existing_block = (
            "\n".join(f"- {s}" for s in existing_edges_summary)
            if existing_edges_summary
            else "(none)"
        )
        prompt = _JUDGE_USER_PROMPT_TEMPLATE.format(
            new_edge_summary=new_edge_summary,
            existing_edges_block=existing_block,
        )

        try:
            raw = await self._llm.chat(
                prompt=prompt,
                system=_JUDGE_SYSTEM_PROMPT,
                model=self._model,
                max_tokens=self._max_tokens,
            )
        except Exception as exc:  # noqa: BLE001  intentional fail-safe
            _logger.warning("conflict judge LLM call failed: %s — fail-safe APPEND_NEW", exc)
            return ConflictVerdict(
                action=ConflictAction.APPEND_NEW,
                reasoning=f"LLM call failed (fail-safe): {exc}",
            )

        try:
            parsed = json.loads(raw)
            action_raw = parsed.get("action", "")
            action = ConflictAction(action_raw)  # 抛 ValueError if not in enum
            reasoning = str(parsed.get("reasoning", ""))
            return ConflictVerdict(action=action, reasoning=reasoning)
        except (json.JSONDecodeError, ValueError) as exc:
            _logger.warning(
                "conflict judge returned unparseable / unknown action: %s — fail-safe APPEND_NEW",
                exc,
            )
            return ConflictVerdict(
                action=ConflictAction.APPEND_NEW,
                reasoning=f"unparseable verdict (fail-safe): {exc}",
            )


# ===== Step 6 Apply Action SQL (spec § 4 Step 6 / 附录 B) =====


def apply_action(
    session: Session,
    verdict: ConflictVerdict,
    existing_edge_ids: list[UUID],
    *,
    user_id: UUID,
    source_node_id: UUID,
    target_node_id: UUID,
    rel_type: str,
    valid_from: datetime,
    valid_to: datetime | None,
    source_episode_id: UUID,
    importance: float,
    reasoning: str,
    properties: dict[str, Any],
) -> ChatMemoryEdge | None:
    """spec § 4 Step 6 — apply 4-action with bi-temporal correctness.

    关键: valid_to (事实演化) vs invalidated_at (系统记错) 字段语义严格分离
    (spec § 2 行 247 categorical). 金融审计场景必要.

    Returns:
        - new ChatMemoryEdge for UPDATE_VALIDITY / CONTRADICT_EXISTING / APPEND_NEW
        - None for NO_OP

    调用方负责事务管理 (commit/rollback). 本函数仅 add + flush.

    Sync session — Plan 1B HierarchicalMemory 用同步 SQLAlchemy session
    (跟 PR #39 / v1.0 一致, contracts § 3 DI 设计).
    """
    if verdict.action == ConflictAction.NO_OP:
        return None

    if verdict.action == ConflictAction.UPDATE_VALIDITY and existing_edge_ids:
        # existing.valid_to = new.valid_from (现实演化, 不动 invalidated_at)
        stmt = (
            update(ChatMemoryEdge)
            .where(ChatMemoryEdge.edge_id.in_(existing_edge_ids))
            .where(ChatMemoryEdge.valid_to.is_(None))  # 仅 update 仍生效的
            .values(valid_to=valid_from)
        )
        session.execute(stmt)
    elif verdict.action == ConflictAction.CONTRADICT_EXISTING and existing_edge_ids:
        # existing.invalidated_at = now() (系统记错, 不动 valid_to)
        contradict_stmt = (
            update(ChatMemoryEdge)
            .where(ChatMemoryEdge.edge_id.in_(existing_edge_ids))
            .where(ChatMemoryEdge.invalidated_at.is_(None))
            .values(invalidated_at=datetime.now(UTC))
        )
        session.execute(contradict_stmt)

    # APPEND_NEW / UPDATE_VALIDITY / CONTRADICT_EXISTING 都 INSERT new
    new_edge = ChatMemoryEdge(
        user_id=user_id,
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        rel_type=rel_type,
        valid_from=valid_from,
        valid_to=valid_to,
        invalidated_at=None,
        source_episode_id=source_episode_id,
        importance=importance,
        reasoning=reasoning,
        properties=properties,
    )
    session.add(new_edge)
    session.flush()
    return new_edge
