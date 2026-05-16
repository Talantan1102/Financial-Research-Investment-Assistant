"""PersonaService 单元测试 — Plan Phase 1.

L0 unit: 全 MagicMock，不触 DB。schema 完整性由 L1 integration 验。
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.memory.models import ChatMemoryPersonaItem


@pytest.mark.unit
def test_persona_item_model_basic_fields() -> None:
    """ChatMemoryPersonaItem 字段齐全 + Index 注册."""
    item = ChatMemoryPersonaItem(
        user_id=uuid4(),
        source="user",
        text="测试条目",
        position=0,
    )
    assert item.source == "user"
    assert item.text == "测试条目"
    assert item.position == 0

    table = ChatMemoryPersonaItem.__table__
    assert table.name == "chat_memory_persona_items"
    index_names = {idx.name for idx in table.indexes}
    assert "ix_persona_items_user_source_pos" in index_names


from unittest.mock import MagicMock  # noqa: E402

from app.memory.persona_service import PersonaService  # noqa: E402


def _mk_session_factory() -> tuple[MagicMock, MagicMock]:
    """构造 mock session_factory 跟 mock session，方便测试 commit/rollback 调用."""
    session = MagicMock()
    session.query.return_value.filter_by.return_value.order_by.return_value.all.return_value = []
    session.query.return_value.filter_by.return_value.first.return_value = None
    factory = MagicMock(return_value=session)
    return factory, session


@pytest.mark.unit
def test_list_items_empty() -> None:
    factory, session = _mk_session_factory()
    service = PersonaService(pg_session_factory=factory)

    result = service.list_items(user_id=uuid4())

    assert result == {"user_declared": [], "agent_inferred": []}
    session.close.assert_called_once()


@pytest.mark.unit
def test_add_item_user_section() -> None:
    factory, session = _mk_session_factory()
    service = PersonaService(pg_session_factory=factory)
    user_id = uuid4()

    item = service.add_item(user_id=user_id, text="保守稳健", target_section="user")

    assert item.source == "user"
    assert item.text == "保守稳健"
    session.add.assert_called_once()
    session.commit.assert_called_once()


@pytest.mark.unit
def test_add_item_strips_and_validates_length() -> None:
    factory, _ = _mk_session_factory()
    service = PersonaService(pg_session_factory=factory)

    with pytest.raises(ValueError, match="empty"):
        service.add_item(user_id=uuid4(), text="   ", target_section="user")

    with pytest.raises(ValueError, match="too long"):
        service.add_item(user_id=uuid4(), text="a" * 501, target_section="user")


@pytest.mark.unit
def test_update_item_text_keeps_source() -> None:
    """改 source='user' 的 item，source 不变."""
    factory, session = _mk_session_factory()
    existing = ChatMemoryPersonaItem(
        item_id=uuid4(),
        user_id=uuid4(),
        source="user",
        text="原文",
        position=0,
    )
    session.query.return_value.filter_by.return_value.first.return_value = existing
    service = PersonaService(pg_session_factory=factory)

    updated = service.update_item(user_id=existing.user_id, item_id=existing.item_id, text="新内容")

    assert updated.source == "user"
    assert updated.text == "新内容"
    session.commit.assert_called_once()


@pytest.mark.unit
def test_update_item_agent_source_upgrades_to_user() -> None:
    """改 agent 区条目自动升级到 user 区 — spec 决策 3."""
    factory, session = _mk_session_factory()
    existing = ChatMemoryPersonaItem(
        item_id=uuid4(),
        user_id=uuid4(),
        source="agent",
        text="原 agent 推断",
        position=5,
    )
    session.query.return_value.filter_by.return_value.first.return_value = existing
    # 模拟查 user 区当前 max position
    max_query = MagicMock()
    max_query.scalar.return_value = 2
    session.query.return_value.filter_by.return_value.with_entities.return_value = max_query
    service = PersonaService(pg_session_factory=factory)

    updated = service.update_item(
        user_id=existing.user_id, item_id=existing.item_id, text="改后内容"
    )

    assert updated.source == "user"
    assert updated.position == 3  # max(2) + 1


@pytest.mark.unit
def test_update_item_not_found_raises() -> None:
    factory, session = _mk_session_factory()
    session.query.return_value.filter_by.return_value.first.return_value = None
    service = PersonaService(pg_session_factory=factory)

    with pytest.raises(LookupError):
        service.update_item(user_id=uuid4(), item_id=uuid4(), text="x")


@pytest.mark.unit
def test_delete_item_calls_delete_and_commit() -> None:
    factory, session = _mk_session_factory()
    existing = ChatMemoryPersonaItem(
        item_id=uuid4(),
        user_id=uuid4(),
        source="user",
        text="待删",
        position=0,
    )
    session.query.return_value.filter_by.return_value.first.return_value = existing
    service = PersonaService(pg_session_factory=factory)

    service.delete_item(user_id=existing.user_id, item_id=existing.item_id)

    session.delete.assert_called_once_with(existing)
    session.commit.assert_called_once()


@pytest.mark.unit
def test_delete_item_not_found_raises() -> None:
    factory, session = _mk_session_factory()
    session.query.return_value.filter_by.return_value.first.return_value = None
    service = PersonaService(pg_session_factory=factory)

    with pytest.raises(LookupError):
        service.delete_item(user_id=uuid4(), item_id=uuid4())


@pytest.mark.unit
def test_apply_agent_append_splits_lines() -> None:
    """多行 content 切多条；prefix `- ` / `* ` 自动去除."""
    factory, session = _mk_session_factory()
    service = PersonaService(pg_session_factory=factory)

    items = service.apply_agent_append(
        user_id=uuid4(), content="- 看好新能源\n* 关注高股息\n空行不算\n"
    )

    assert [i.text for i in items] == ["看好新能源", "关注高股息", "空行不算"]
    assert all(i.source == "agent" for i in items)
    assert session.add.call_count == 3
    session.commit.assert_called_once()


@pytest.mark.unit
def test_apply_agent_append_mixed_bullets_and_blank_lines() -> None:
    """混合 -/* prefix + 多个空行 + 缩进 — 容忍 LLM 输出变体."""
    factory, session = _mk_session_factory()
    service = PersonaService(pg_session_factory=factory)

    items = service.apply_agent_append(
        user_id=uuid4(),
        content="\n\n- foo\n\n* bar\n   \n  - baz\n",
    )

    assert [i.text for i in items] == ["foo", "bar", "baz"]
    assert all(i.source == "agent" for i in items)
    assert session.add.call_count == 3


@pytest.mark.unit
def test_apply_agent_append_empty_noop() -> None:
    factory, session = _mk_session_factory()
    service = PersonaService(pg_session_factory=factory)
    items = service.apply_agent_append(user_id=uuid4(), content="   \n  ")
    assert items == []
    session.add.assert_not_called()


@pytest.mark.unit
def test_apply_agent_replace_match_agent_item() -> None:
    """命中 source='agent' 的 item → 改 text，source 保持 agent."""
    factory, session = _mk_session_factory()
    target = ChatMemoryPersonaItem(
        item_id=uuid4(),
        user_id=uuid4(),
        source="agent",
        text="保守",
        position=0,
    )
    session.query.return_value.filter_by.return_value.order_by.return_value.all.return_value = [
        target
    ]
    service = PersonaService(pg_session_factory=factory)

    items = service.apply_agent_replace(
        user_id=target.user_id, old_content="保守", new_content="偏成长"
    )

    assert items[0].text == "偏成长"
    assert items[0].source == "agent"
    # 同一 item_id 验证走 match 路径而非 fallback append（fallback 会创建新 UUID）
    assert items[0].item_id == target.item_id
    session.commit.assert_called_once()


@pytest.mark.unit
def test_apply_agent_replace_never_match_user_item() -> None:
    """即使 text 一致也不能动 source='user' 的 item — 双轨保护."""
    factory, session = _mk_session_factory()
    user_item = ChatMemoryPersonaItem(
        item_id=uuid4(),
        user_id=uuid4(),
        source="user",
        text="保守稳健",
        position=0,
    )
    # filter_by(source='agent') → order_by → all 返回空
    session.query.return_value.filter_by.return_value.order_by.return_value.all.return_value = []
    service = PersonaService(pg_session_factory=factory)

    items = service.apply_agent_replace(
        user_id=user_item.user_id, old_content="保守稳健", new_content="激进"
    )

    # fallback: 没匹配到 → append 一条新 agent item
    assert len(items) == 1
    assert items[0].source == "agent"
    assert items[0].text == "激进"


@pytest.mark.unit
def test_apply_agent_replace_no_match_falls_back_to_append() -> None:
    """spec § 8.2: 未找到 → 降级为 apply_agent_append + log warn."""
    factory, session = _mk_session_factory()
    session.query.return_value.filter_by.return_value.order_by.return_value.all.return_value = []
    service = PersonaService(pg_session_factory=factory)

    items = service.apply_agent_replace(user_id=uuid4(), old_content="不存在的", new_content="新条")

    assert len(items) == 1
    assert items[0].text == "新条"
    assert items[0].source == "agent"
