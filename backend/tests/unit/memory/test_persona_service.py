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
    assert session.add.call_count >= 1  # ≥1: item add + _sync_to_working_block block add
    assert session.commit.call_count == 2  # 1 CRUD commit + 1 sync commit


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

    updated = service.update_item(user_id=existing.user_id, item_id=existing.item_id, text="新内容")  # type: ignore[arg-type]

    assert updated.source == "user"
    assert updated.text == "新内容"
    assert session.commit.call_count == 2  # 1 CRUD commit + 1 sync commit


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
        user_id=existing.user_id,  # type: ignore[arg-type]
        item_id=existing.item_id,  # type: ignore[arg-type]
        text="改后内容",
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

    service.delete_item(user_id=existing.user_id, item_id=existing.item_id)  # type: ignore[arg-type]

    session.delete.assert_called_once_with(existing)
    assert session.commit.call_count == 2  # 1 CRUD commit + 1 sync commit


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
    assert session.add.call_count >= 3  # 3 items + _sync_to_working_block block add
    assert session.commit.call_count == 2  # 1 CRUD commit + 1 sync commit


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
    assert session.add.call_count >= 3  # 3 items + _sync_to_working_block block add


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
        user_id=target.user_id,  # type: ignore[arg-type]
        old_content="保守",
        new_content="偏成长",
    )

    assert items[0].text == "偏成长"
    assert items[0].source == "agent"
    # 同一 item_id 验证走 match 路径而非 fallback append（fallback 会创建新 UUID）
    assert items[0].item_id == target.item_id
    assert session.commit.call_count == 2  # 1 CRUD commit + 1 sync commit


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
        user_id=user_item.user_id,  # type: ignore[arg-type]
        old_content="保守稳健",
        new_content="激进",
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


from app.memory.models import ChatMemoryWorkingBlock  # noqa: E402


@pytest.mark.unit
def test_render_to_markdown_uses_items() -> None:
    """render_to_markdown 接 persona_items_md.render_items_to_markdown."""
    factory, session = _mk_session_factory()
    user_id = uuid4()
    user_rows = [
        ChatMemoryPersonaItem(user_id=user_id, source="user", text="A", position=0),
    ]
    agent_rows = [
        ChatMemoryPersonaItem(user_id=user_id, source="agent", text="B", position=0),
        ChatMemoryPersonaItem(user_id=user_id, source="agent", text="C", position=1),
    ]

    def _query_dispatch(*_a: object, **_kw: object) -> MagicMock:
        m = MagicMock()
        # 简化：分别针对 user / agent filter_by 返回不同 mock
        m.filter_by.side_effect = lambda **kw: {
            "user": MagicMock(order_by=lambda *_a, **_kw: MagicMock(all=lambda: user_rows)),
            "agent": MagicMock(order_by=lambda *_a, **_kw: MagicMock(all=lambda: agent_rows)),
        }[kw["source"]]
        return m

    session.query.side_effect = _query_dispatch
    service = PersonaService(pg_session_factory=factory)

    md = service.render_to_markdown(user_id=user_id)

    assert "- A" in md
    assert "- B" in md
    assert "- C" in md
    assert md.index("- A") < md.index("- B")  # user 区先于 agent 区


@pytest.mark.unit
def test_sync_to_working_block_upserts_existing() -> None:
    """已有 persona working_block → 更新 content."""
    factory, session = _mk_session_factory()
    user_id = uuid4()
    existing_block = ChatMemoryWorkingBlock(
        user_id=user_id, block_name="persona", content="old", max_tokens=500, token_count=0
    )

    def _block_query(*_a: object, **_kw: object) -> MagicMock:
        m = MagicMock()
        m.filter_by.return_value.first.return_value = existing_block
        return m

    def _items_query(*_a: object, **_kw: object) -> MagicMock:
        m = MagicMock()
        m.filter_by.return_value.order_by.return_value.all.return_value = []
        return m

    call_count = {"n": 0}

    def _dispatch(model_cls: object) -> MagicMock:
        call_count["n"] += 1
        if model_cls is ChatMemoryWorkingBlock:
            return _block_query()
        return _items_query()

    session.query.side_effect = _dispatch
    service = PersonaService(pg_session_factory=factory)

    service._sync_to_working_block(session=None, user_id=user_id)

    assert "## 你声明的" in existing_block.content
    session.commit.assert_called()


@pytest.mark.unit
def test_sync_to_working_block_inserts_new() -> None:
    """无既有 persona block → insert."""
    factory, session = _mk_session_factory()

    def _block_query(*_a: object, **_kw: object) -> MagicMock:
        m = MagicMock()
        m.filter_by.return_value.first.return_value = None  # 不存在
        return m

    def _items_query(*_a: object, **_kw: object) -> MagicMock:
        m = MagicMock()
        m.filter_by.return_value.order_by.return_value.all.return_value = []
        return m

    def _dispatch(model_cls: object) -> MagicMock:
        if model_cls is ChatMemoryWorkingBlock:
            return _block_query()
        return _items_query()

    session.query.side_effect = _dispatch
    service = PersonaService(pg_session_factory=factory)

    service._sync_to_working_block(session=None, user_id=uuid4())

    session.add.assert_called()
    session.commit.assert_called()


@pytest.mark.unit
def test_sync_to_working_block_rolls_back_on_commit_failure() -> None:
    """sync 上的 commit 失败时调用 rollback。"""
    from sqlalchemy.exc import OperationalError

    factory, session = _mk_session_factory()

    def _block_query(*_a: object, **_kw: object) -> MagicMock:
        m = MagicMock()
        m.filter_by.return_value.first.return_value = None
        return m

    def _items_query(*_a: object, **_kw: object) -> MagicMock:
        m = MagicMock()
        m.filter_by.return_value.order_by.return_value.all.return_value = []
        return m

    def _dispatch(model_cls: object) -> MagicMock:
        if model_cls is ChatMemoryWorkingBlock:
            return _block_query()
        return _items_query()

    session.query.side_effect = _dispatch
    session.commit.side_effect = OperationalError("DB down", None, Exception("simulated"))
    service = PersonaService(pg_session_factory=factory)

    with pytest.raises(OperationalError):
        service._sync_to_working_block(session=None, user_id=uuid4())

    session.rollback.assert_called_once()
