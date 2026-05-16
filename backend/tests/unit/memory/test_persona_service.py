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
