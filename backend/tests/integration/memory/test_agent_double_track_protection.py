"""Plan Task 19 — agent 试图改 user 区被服务层拒绝 + fallback 落 agent 区."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

import pytest
from app.memory.persona_service import PersonaService

pytestmark = pytest.mark.integration


def test_agent_replace_user_text_falls_back_to_agent_append(
    pg_memory_session_factory: Any,
    seed_persona_user: Callable[..., None],
) -> None:
    svc = PersonaService(pg_session_factory=pg_memory_session_factory)
    user_id = uuid4()
    seed_persona_user(user_id, prefix="dtrack_repl_")

    # 1. user 声明一条
    user_item = svc.add_item(user_id=user_id, text="风险偏好：保守稳健", target_section="user")

    # 2. agent 通过 apply_agent_replace 试图改 user 区那条
    items = svc.apply_agent_replace(
        user_id=user_id,
        old_content="风险偏好：保守稳健",
        new_content="风险偏好：激进进取",
    )

    # 3. user 区那条原封不动
    assert items[0].source == "agent"
    assert items[0].text == "风险偏好：激进进取"

    result = svc.list_items(user_id=user_id)
    assert len(result["user_declared"]) == 1
    assert result["user_declared"][0].item_id == user_item.item_id
    assert result["user_declared"][0].text == "风险偏好：保守稳健"
    # agent 区新增了一条 (fallback append)
    assert len(result["agent_inferred"]) == 1
    assert result["agent_inferred"][0].text == "风险偏好：激进进取"


def test_agent_append_never_writes_to_user_section(
    pg_memory_session_factory: Any,
    seed_persona_user: Callable[..., None],
) -> None:
    svc = PersonaService(pg_session_factory=pg_memory_session_factory)
    user_id = uuid4()
    seed_persona_user(user_id, prefix="dtrack_app_")

    svc.apply_agent_append(user_id=user_id, content="- 关注新能源\n- 偏好长期持有\n")

    result = svc.list_items(user_id=user_id)
    assert len(result["user_declared"]) == 0
    assert len(result["agent_inferred"]) == 2
    assert all(i.source == "agent" for i in result["agent_inferred"])
