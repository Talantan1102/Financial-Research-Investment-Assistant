"""L0 unit tests for AGE sync — rel_type whitelist defense-in-depth.

完整 Cypher CREATE/MATCH 测试在 L1 (test_age_sync_e2e.py), AGE 不可用时 skip.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.memory.age_sync import age_create_edge, age_merge_node


def test_age_create_edge_invalid_rel_type_raises_value_error() -> None:
    """rel_type 不在 11 类 elabel → 直接 ValueError, 不调底层 Cypher."""
    with pytest.raises(ValueError, match="rel_type"):
        age_create_edge(
            session=None,  # type: ignore[arg-type]  validation precedes session use
            edge_id=uuid4(),
            source_node_id=uuid4(),
            target_node_id=uuid4(),
            rel_type="LOVES",  # 非 11 类
        )


def test_age_merge_node_invalid_entity_type_raises_value_error() -> None:
    """entity_type 不在 7 类 vlabel → ValueError."""
    with pytest.raises(ValueError, match="entity_type"):
        age_merge_node(
            session=None,  # type: ignore[arg-type]
            node_id=uuid4(),
            entity_type="Bond",  # 非 7 类
        )


def test_age_create_edge_valid_rel_type_proceeds() -> None:
    """Valid rel_type 时进入 session.execute (用 dummy session 验证不抛 ValueError).

    完整 Cypher 行为校验在 L1 e2e 测试.
    """

    class _DummySession:
        def execute(self, _stmt: object) -> None:
            return None

    age_create_edge(
        session=_DummySession(),  # type: ignore[arg-type]
        edge_id=uuid4(),
        source_node_id=uuid4(),
        target_node_id=uuid4(),
        rel_type="HOLDS",
    )
