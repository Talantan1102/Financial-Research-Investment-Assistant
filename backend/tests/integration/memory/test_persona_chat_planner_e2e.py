"""持仓改动 → ChatPlanner 下轮 prompt 含新内容 — 验证端到端 wire.

Plan Task 10: user 加 persona 条目 → PersonaService._sync_to_working_block 写回
chat_memory_working_blocks → load_memory_tool_usage_prompt 读取 → prompt 含新条目。

这是 persona-ui feature 最重要的 e2e 集成测试：若通过，代理下一轮真的能看到更新后的画像。

Note: `_seed_user` helper consolidated to `seed_persona_user` fixture in conftest (Task 19).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

import pytest
from app.agents.chat.prompt_loader import load_memory_tool_usage_prompt
from app.memory.hierarchical import HierarchicalMemory
from app.memory.persona_service import PersonaService

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_user_persona_change_visible_in_next_prompt(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Any,
    seed_persona_user: Callable[..., None],
) -> None:
    """用户加一条 persona → 下一轮 ChatPlanner prompt 含该条目."""
    user_id = uuid4()
    session_id = uuid4()
    seed_persona_user(user_id, prefix="cp_e2e_")

    persona_svc = PersonaService(pg_session_factory=pg_memory_session_factory)

    # 用户加一条
    persona_svc.add_item(user_id=user_id, text="风险偏好：保守稳健", target_section="user")

    # 构造 HierarchicalMemory（最小 DI — 只需 pg_session_factory 走 persona path）
    # age_executor / milvus_client / embed_service / llm_extractor / llm_judge 全是
    # Any 类型，传 None 安全；persona path 不触碰这些 DI。
    memory = HierarchicalMemory(
        pg_session_factory=pg_memory_session_factory,
        age_executor=None,
        milvus_client=None,
        embed_service=None,
        llm_extractor=None,
        llm_judge=None,
    )

    rendered = await load_memory_tool_usage_prompt(
        memory=memory, user_id=user_id, session_id=session_id
    )

    assert "风险偏好：保守稳健" in rendered
    assert "## 你声明的" in rendered
