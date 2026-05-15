"""Working blocks → markdown 渲染层.

Phase 1 — self-managed wire 用,从 c5 已 ship 的 HierarchicalMemory.get_working_blocks
拉 persona / scratchpad block,渲染成 markdown 字符串供 chat_planner prompt 注入。

设计要点:
- 纯函数 + async(因 get_working_blocks 是 async)
- 失败隔离:DB 错误返回 placeholder,不让 chat 崩
- Phase 4 把 scratchpad 拆出独立表后,本模块再加 render_scratchpad_from_session(session_id)
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)


_PERSONA_EMPTY = "(暂无画像 — 用户首次对话,等待信号沉淀)"
_SCRATCHPAD_EMPTY = "(本 session 暂无便签)"


async def render_persona_markdown(memory: Any, user_id: UUID) -> str:
    """渲染 persona working block 为 markdown 字符串.

    Args:
        memory: HierarchicalMemory 实例(Memory Protocol).
        user_id: 用户 UUID.

    Returns:
        markdown 字符串. 空 block 返回 placeholder; DB 错误返回 error placeholder.
    """
    try:
        blocks = await memory.get_working_blocks(user_id)
    except Exception as exc:
        logger.warning("render_persona_markdown: get_working_blocks failed: %s", exc)
        return f"(画像渲染失败 — {type(exc).__name__})"

    block = blocks.get("persona")
    if block is None or not block.content:
        return _PERSONA_EMPTY
    return str(block.content)


async def render_scratchpad_markdown(memory: Any, user_id: UUID) -> str:
    """渲染 scratchpad working block 为 markdown.

    Phase 1 沿用 c5 working_blocks 表(user-scoped, 不是 session-scoped).
    Phase 4 拆出独立 chat_scratchpad 表后,签名会从 user_id 改成 session_id.
    """
    try:
        blocks = await memory.get_working_blocks(user_id)
    except Exception as exc:
        logger.warning("render_scratchpad_markdown: get_working_blocks failed: %s", exc)
        return f"(便签渲染失败 — {type(exc).__name__})"

    block = blocks.get("scratchpad")
    if block is None or not block.content:
        return _SCRATCHPAD_EMPTY
    return str(block.content)
