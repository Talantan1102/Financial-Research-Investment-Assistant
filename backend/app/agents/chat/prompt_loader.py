"""Memory tool usage prompt loader.

Phase 1 — self-managed wire. 加载 prompts/memory_tool_usage.md, 用 render.py
函数填占位符 {{persona_block}} / {{scratchpad_block}}, 返回完整字符串供
chat_planner._build_chat_prompt 注入.

设计要点:
- 模块加载时缓存模板内容(模板是静态文件,不会运行时变);
- 占位符 sentinel "{{persona_block}}" / "{{scratchpad_block}}" 必须存在,
  缺一就 raise(防 silent miss);
- DB 错误传递给 render.py 处理(它会返回 error placeholder).
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from app.memory.protocol import Memory
from app.memory.render import (
    render_persona_markdown,
    render_scratchpad_markdown,
)

_TEMPLATE_PATH = Path(__file__).resolve().parent / "prompts" / "memory_tool_usage.md"

_PERSONA_PLACEHOLDER = "{{persona_block}}"
_SCRATCHPAD_PLACEHOLDER = "{{scratchpad_block}}"

# 启动时一次性加载
_TEMPLATE_TEXT: str = _TEMPLATE_PATH.read_text(encoding="utf-8")

# Sanity check (模块导入即触发,防止线上才发现模板坏)
if _PERSONA_PLACEHOLDER not in _TEMPLATE_TEXT:
    raise RuntimeError(f"{_TEMPLATE_PATH}: missing placeholder {_PERSONA_PLACEHOLDER!r}")
if _SCRATCHPAD_PLACEHOLDER not in _TEMPLATE_TEXT:
    raise RuntimeError(f"{_TEMPLATE_PATH}: missing placeholder {_SCRATCHPAD_PLACEHOLDER!r}")


async def load_memory_tool_usage_prompt(
    memory: Memory,
    user_id: UUID,
    session_id: UUID,  # noqa: ARG001 — Phase 4 will use this for chat_scratchpad
) -> str:
    """Load memory_tool_usage.md template + render persona/scratchpad blocks.

    Args:
        memory: Memory Protocol 实例.
        user_id: 用户 UUID(画像层 + Phase 1 期 scratchpad 也按 user 取).
        session_id: session UUID(Phase 1 暂未使用, Phase 4 接 chat_scratchpad 表后用).

    Returns:
        完整 memory tool usage prompt 字符串, 占位符已替换.
    """
    persona = await render_persona_markdown(memory, user_id)
    scratchpad = await render_scratchpad_markdown(memory, user_id)

    rendered = _TEMPLATE_TEXT
    rendered = rendered.replace(_PERSONA_PLACEHOLDER, persona)
    rendered = rendered.replace(_SCRATCHPAD_PLACEHOLDER, scratchpad)
    return rendered
