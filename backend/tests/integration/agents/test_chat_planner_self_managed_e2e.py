"""L1 — chat_planner self-managed memory prompt e2e.

Spec § 7 Phase 1 DoD — verify:
  1. session 起手 prompt 头部含 [画像] / [便签] 内容
  2. 3 条 domain-specific save triggers 可见
  3. 失败隔离: memory 抛错时 chat 仍能产生 prompt
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from app.agents.chat_planner import ChatPlanner
from app.agents.schemas import ChatState


@pytest.fixture
def fake_llm() -> MagicMock:
    return MagicMock()


def _make_state(user_message: str = "我想加仓 500 股茅台") -> ChatState:
    """ChatState 工厂. Pydantic 必填 request_id / trace_request_id."""
    return ChatState(
        user_id=str(uuid4()),
        session_id=str(uuid4()),
        user_message=user_message,
        history=[],
        request_id=str(uuid4()),
        trace_request_id=str(uuid4()),
    )


@pytest.mark.asyncio
async def test_e2e_prompt_contains_persona_scratchpad_triggers_and_user_msg(
    fake_llm: MagicMock,
) -> None:
    """端到端: 完整 chat_planner build_chat_prompt 输出全部必要段."""
    persona_block = MagicMock()
    persona_block.content = "- 风险偏好: 稳健\n- 资产规模: 200 万"
    scratch_block = MagicMock()
    scratch_block.content = "- 本轮在追立讯精密 002475"
    memory = MagicMock()
    memory.get_working_blocks = AsyncMock(
        return_value={"persona": persona_block, "scratchpad": scratch_block}
    )

    planner = ChatPlanner(
        llm=fake_llm,
        available_tools=["fetch_quote", "archival_memory_insert"],
        memory=memory,
    )

    state = _make_state()
    prompt = await planner._build_chat_prompt(state)

    # 1. memory block 段 (Tier 1 + Tier 2 + Tier 3)
    assert "Memory Tool Usage" in prompt
    assert "Tier 1" in prompt
    assert "Tier 2" in prompt
    assert "Tier 3" in prompt

    # 2. persona + scratchpad 实际内容
    assert "风险偏好: 稳健" in prompt
    assert "立讯精密" in prompt

    # 3. 3 条 domain-specific save triggers
    assert "投资偏好" in prompt
    assert "HOLDS" in prompt or "加仓" in prompt
    assert "EXPRESSED_VIEW" in prompt or "表态" in prompt

    # 4. 反例 Don't save
    assert "一次性" in prompt or "闲聊" in prompt

    # 5. 主 prompt 段 (planner template)
    assert "用户当前问题:" in prompt
    assert "我想加仓 500 股茅台" in prompt

    # 6. 顺序: memory block 在主 prompt 之前
    assert prompt.index("Memory Tool Usage") < prompt.index("用户当前问题:")


@pytest.mark.asyncio
async def test_e2e_no_memory_di_falls_back_gracefully(fake_llm: MagicMock) -> None:
    """memory=None 时, prompt 不含 memory block 但主 prompt 完整 (向后兼容)."""
    planner = ChatPlanner(
        llm=fake_llm,
        available_tools=["fetch_quote"],
        memory=None,
    )

    state = _make_state()
    prompt = await planner._build_chat_prompt(state)

    # 主 prompt 仍然完整
    assert "用户当前问题:" in prompt
    assert "我想加仓 500 股茅台" in prompt
    # memory block 段不存在
    assert "Memory Tool Usage" not in prompt


@pytest.mark.asyncio
async def test_e2e_memory_db_error_isolated(fake_llm: MagicMock) -> None:
    """memory.get_working_blocks 抛 DB error 时, chat 仍能产生 prompt."""
    memory = MagicMock()
    memory.get_working_blocks = AsyncMock(side_effect=RuntimeError("PG down"))

    planner = ChatPlanner(
        llm=fake_llm,
        available_tools=["fetch_quote"],
        memory=memory,
    )

    state = _make_state()
    prompt = await planner._build_chat_prompt(state)

    # 主 prompt 必须能产生
    assert "用户当前问题:" in prompt
    # memory section 出现, 但内容是 error placeholder (render.py 层处理)
    assert "Memory Tool Usage" in prompt
    assert "画像渲染失败" in prompt or "便签渲染失败" in prompt


@pytest.mark.asyncio
async def test_e2e_empty_working_blocks_uses_placeholders(
    fake_llm: MagicMock,
) -> None:
    """空 working_blocks → 用人类可读 placeholder."""
    memory = MagicMock()
    memory.get_working_blocks = AsyncMock(return_value={})

    planner = ChatPlanner(
        llm=fake_llm,
        available_tools=["fetch_quote"],
        memory=memory,
    )

    state = _make_state()
    prompt = await planner._build_chat_prompt(state)

    assert "(暂无画像" in prompt
    assert "(本 session 暂无便签)" in prompt
