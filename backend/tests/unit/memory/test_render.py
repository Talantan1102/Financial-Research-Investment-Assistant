"""L0 — render_persona_markdown / render_scratchpad_markdown 纯函数."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from app.memory.render import (
    render_persona_markdown,
    render_scratchpad_markdown,
)


@pytest.fixture
def fake_user_id() -> UUID:
    return UUID("11111111-1111-1111-1111-111111111111")


@pytest.mark.asyncio
async def test_render_persona_markdown_empty(fake_user_id: UUID) -> None:
    """空 working_blocks 返回 placeholder 字符串."""
    memory = MagicMock()
    memory.get_working_blocks = AsyncMock(return_value={})

    result = await render_persona_markdown(memory, fake_user_id)
    assert result == "(暂无画像 — 用户首次对话,等待信号沉淀)"


@pytest.mark.asyncio
async def test_render_persona_markdown_with_content(fake_user_id: UUID) -> None:
    """有 persona block 渲染为 markdown."""
    block = MagicMock()
    block.content = "- 风险偏好: 稳健\n- 不碰: ST / 高估值"
    memory = MagicMock()
    memory.get_working_blocks = AsyncMock(return_value={"persona": block})

    result = await render_persona_markdown(memory, fake_user_id)
    assert "风险偏好: 稳健" in result
    assert "不碰: ST" in result


@pytest.mark.asyncio
async def test_render_scratchpad_markdown_empty(fake_user_id: UUID) -> None:
    """空 scratchpad 返回 placeholder."""
    memory = MagicMock()
    memory.get_working_blocks = AsyncMock(return_value={})

    result = await render_scratchpad_markdown(memory, fake_user_id)
    assert result == "(本 session 暂无便签)"


@pytest.mark.asyncio
async def test_render_scratchpad_markdown_with_content(fake_user_id: UUID) -> None:
    """有 scratchpad block 渲染."""
    block = MagicMock()
    block.content = "- 本轮在追立讯精密 002475"
    memory = MagicMock()
    memory.get_working_blocks = AsyncMock(return_value={"scratchpad": block})

    result = await render_scratchpad_markdown(memory, fake_user_id)
    assert "立讯精密" in result


@pytest.mark.asyncio
async def test_render_persona_markdown_handles_db_error(fake_user_id: UUID) -> None:
    """get_working_blocks 抛错时返回 placeholder,不让 chat 崩."""
    memory = MagicMock()
    memory.get_working_blocks = AsyncMock(side_effect=RuntimeError("DB down"))

    result = await render_persona_markdown(memory, fake_user_id)
    assert "(画像渲染失败" in result
