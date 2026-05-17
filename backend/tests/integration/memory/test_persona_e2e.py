"""真 PG e2e — Plan Task 9.

复用 pg_memory_session_factory fixture (backend/tests/integration/memory/conftest.py).

Note: chat_memory_persona_items.user_id FK → users.id, so each test must seed
a user row before inserting persona items. `seed_persona_user` fixture in
conftest handles this (Task 19 consolidation).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

import pytest
from app.memory.models import ChatMemoryPersonaItem, ChatMemoryWorkingBlock
from app.memory.persona_service import PersonaService

pytestmark = pytest.mark.integration


def _service(factory: Any) -> PersonaService:
    return PersonaService(pg_session_factory=factory)


def test_full_lifecycle_user_add_agent_append_upgrade(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Any,
    seed_persona_user: Callable[..., None],
) -> None:
    svc = _service(pg_memory_session_factory)
    user_id = uuid4()
    seed_persona_user(user_id, prefix="pe2e_")

    # 1. user 加一条
    u1 = svc.add_item(user_id=user_id, text="保守稳健", target_section="user")
    assert u1.source == "user"

    # 2. agent 通过转译层加两条
    appended = svc.apply_agent_append(user_id=user_id, content="- 关注新能源\n- 高股息消费\n")
    assert len(appended) == 2

    # 3. user 改 agent 区第一条 → 升级
    upgraded = svc.update_item(
        user_id=user_id,
        item_id=appended[0].item_id,  # type: ignore[arg-type]
        text="关注新能源 + 储能",
    )
    assert upgraded.source == "user"

    # 4. list 验证
    result = svc.list_items(user_id=user_id)
    assert len(result["user_declared"]) == 2
    assert len(result["agent_inferred"]) == 1
    user_texts = {i.text for i in result["user_declared"]}
    assert user_texts == {"保守稳健", "关注新能源 + 储能"}

    # 5. render_to_markdown 跟状态一致
    md = svc.render_to_markdown(user_id=user_id)
    assert "## 你声明的" in md
    assert "保守稳健" in md
    assert "关注新能源 + 储能" in md
    assert "高股息消费" in md

    # 6. _sync_to_working_block 应已写回 working_blocks
    session = pg_memory_session_factory()
    try:
        block = (
            session.query(ChatMemoryWorkingBlock)
            .filter_by(user_id=user_id, block_name="persona")
            .first()
        )
        assert block is not None
        assert "保守稳健" in block.content
    finally:
        session.close()


def test_cross_user_isolation(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Any,
    seed_persona_user: Callable[..., None],
) -> None:
    svc = _service(pg_memory_session_factory)
    user_a = uuid4()
    user_b = uuid4()
    seed_persona_user(user_a, prefix="pe2e_a_")
    seed_persona_user(user_b, prefix="pe2e_b_")

    svc.add_item(user_id=user_a, text="A 的条", target_section="user")
    svc.add_item(user_id=user_b, text="B 的条", target_section="user")

    a_result = svc.list_items(user_id=user_a)
    b_result = svc.list_items(user_id=user_b)

    assert {i.text for i in a_result["user_declared"]} == {"A 的条"}
    assert {i.text for i in b_result["user_declared"]} == {"B 的条"}


def test_apply_agent_replace_fallback_to_append(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Any,
    seed_persona_user: Callable[..., None],
) -> None:
    svc = _service(pg_memory_session_factory)
    user_id = uuid4()
    seed_persona_user(user_id, prefix="pe2e_repl_")

    # 没有任何 agent item → replace 应 fallback 为 append
    items = svc.apply_agent_replace(user_id=user_id, old_content="不存在", new_content="新加的")
    assert len(items) == 1
    assert items[0].source == "agent"
    assert items[0].text == "新加的"


def test_delete_item_removes_row(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Any,
    seed_persona_user: Callable[..., None],
) -> None:
    svc = _service(pg_memory_session_factory)
    user_id = uuid4()
    seed_persona_user(user_id, prefix="pe2e_del_")

    item = svc.add_item(user_id=user_id, text="待删", target_section="user")

    svc.delete_item(user_id=user_id, item_id=item.item_id)  # type: ignore[arg-type]

    result = svc.list_items(user_id=user_id)
    assert result["user_declared"] == []

    # 确认 DB 真的删了
    session = pg_memory_session_factory()
    try:
        remaining = session.query(ChatMemoryPersonaItem).filter_by(item_id=item.item_id).first()
        assert remaining is None
    finally:
        session.close()
