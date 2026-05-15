"""L0 — load_memory_tool_usage_prompt 模板加载 + 占位符替换."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from app.agents.chat.prompt_loader import load_memory_tool_usage_prompt


@pytest.fixture
def fake_user_id() -> UUID:
    return UUID("11111111-1111-1111-1111-111111111111")


@pytest.fixture
def fake_session_id() -> UUID:
    return UUID("22222222-2222-2222-2222-222222222222")


@pytest.mark.asyncio
async def test_load_returns_string_containing_template_content(
    fake_user_id: UUID, fake_session_id: UUID
) -> None:
    memory = MagicMock()
    memory.get_working_blocks = AsyncMock(return_value={})

    result = await load_memory_tool_usage_prompt(
        memory=memory, user_id=fake_user_id, session_id=fake_session_id
    )

    # 含模板原文关键段
    assert "Memory Tool Usage" in result
    assert "Tier 1" in result
    assert "Tier 2" in result
    # 含 Phase 1 新增的 domain-specific save triggers (Task 1)
    assert "投资偏好" in result
    assert "Don't save" in result or "不要 save" in result


@pytest.mark.asyncio
async def test_load_replaces_persona_placeholder(fake_user_id: UUID, fake_session_id: UUID) -> None:
    """{{persona_block}} 必须被替换成实际内容."""
    block = MagicMock()
    block.content = "- 风险偏好: 稳健"
    memory = MagicMock()
    memory.get_working_blocks = AsyncMock(return_value={"persona": block})

    result = await load_memory_tool_usage_prompt(
        memory=memory, user_id=fake_user_id, session_id=fake_session_id
    )

    # 占位符不能残留
    assert "{{persona_block}}" not in result
    assert "{{scratchpad_block}}" not in result
    # 实际内容必须出现
    assert "风险偏好: 稳健" in result


@pytest.mark.asyncio
async def test_load_replaces_scratchpad_placeholder(
    fake_user_id: UUID, fake_session_id: UUID
) -> None:
    block = MagicMock()
    block.content = "- 本轮在追立讯精密"
    memory = MagicMock()
    memory.get_working_blocks = AsyncMock(return_value={"scratchpad": block})

    result = await load_memory_tool_usage_prompt(
        memory=memory, user_id=fake_user_id, session_id=fake_session_id
    )

    assert "{{scratchpad_block}}" not in result
    assert "立讯精密" in result


@pytest.mark.asyncio
async def test_load_uses_empty_placeholders_when_no_blocks(
    fake_user_id: UUID, fake_session_id: UUID
) -> None:
    """空 blocks 替换为人类可读的 placeholder, 不是空字符串."""
    memory = MagicMock()
    memory.get_working_blocks = AsyncMock(return_value={})

    result = await load_memory_tool_usage_prompt(
        memory=memory, user_id=fake_user_id, session_id=fake_session_id
    )

    assert "(暂无画像" in result
    assert "(本 session 暂无便签)" in result
