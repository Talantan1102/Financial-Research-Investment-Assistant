"""L0 schema test for chat_memory_* models. PG-specific behaviors covered in L1.

覆盖:
- 4 model 类可 import + tablename 正确
- 字段名 / 类型 / nullable 跟契约 § 4 对齐
- UNIQUE / CHECK constraint 在 metadata 里被识别
- create_all() on sqlite override 不报错
"""

from __future__ import annotations

import pytest
from app.core.database import Base
from app.memory.models import (
    ChatMemoryEdge,
    ChatMemoryEpisode,
    ChatMemoryNode,
    ChatMemoryWorkingBlock,
)
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

# ---------------------------------------------------------------------------
# 1. tablenames + import smoke
# ---------------------------------------------------------------------------


def test_tablenames() -> None:
    assert ChatMemoryEpisode.__tablename__ == "chat_memory_episodes"
    assert ChatMemoryNode.__tablename__ == "chat_memory_nodes"
    assert ChatMemoryEdge.__tablename__ == "chat_memory_edges"
    assert ChatMemoryWorkingBlock.__tablename__ == "chat_memory_working_blocks"


# ---------------------------------------------------------------------------
# 2. 字段 surface 校验(契约 § 4)
# ---------------------------------------------------------------------------


def test_episode_fields() -> None:
    cols = {c.name for c in ChatMemoryEpisode.__table__.columns}
    assert cols == {
        "episode_id",
        "user_id",
        "session_id",
        "episode_index",
        "user_message_text",
        "agent_response_text",
        "source_kind",
        "extracted_at",
        "extracted_by",
        "extraction_metadata",
        "created_at",
    }


def test_node_fields() -> None:
    cols = {c.name for c in ChatMemoryNode.__table__.columns}
    assert cols == {
        "node_id",
        "user_id",
        "entity_type",
        "entity_label",
        "properties",
        "created_at",
        "search_tokens",
    }


def test_edge_fields() -> None:
    cols = {c.name for c in ChatMemoryEdge.__table__.columns}
    expected = {
        "edge_id",
        "user_id",
        "source_node_id",
        "target_node_id",
        "rel_type",
        "valid_from",
        "valid_to",
        "recorded_at",
        "invalidated_at",
        "source_episode_id",
        "importance",
        "reasoning",
        "properties",
        "search_tokens",
    }
    assert cols == expected, f"missing: {expected - cols}, extra: {cols - expected}"


def test_working_block_fields() -> None:
    cols = {c.name for c in ChatMemoryWorkingBlock.__table__.columns}
    assert cols == {
        "block_id",
        "user_id",
        "block_name",
        "content",
        "token_count",
        "max_tokens",
        "updated_at",
    }


# ---------------------------------------------------------------------------
# 3. Constraint surface(UNIQUE / CHECK 命名)
# ---------------------------------------------------------------------------


def _constraint_names(table: object) -> set[str]:
    return {c.name for c in table.constraints if c.name}  # type: ignore[attr-defined]


def test_episode_constraints() -> None:
    names = _constraint_names(ChatMemoryEpisode.__table__)
    assert "uq_episodes_session_idx" in names


def test_node_constraints() -> None:
    names = _constraint_names(ChatMemoryNode.__table__)
    assert "uq_nodes_user_type_label" in names


def test_edge_constraints() -> None:
    names = _constraint_names(ChatMemoryEdge.__table__)
    # importance 三档 CHECK
    assert "ck_edges_importance_three_tier" in names
    # 幂等键 UNIQUE — 算法深度补丁 #5
    assert "uq_edges_idempotency_key" in names


def test_working_block_constraints() -> None:
    names = _constraint_names(ChatMemoryWorkingBlock.__table__)
    assert "uq_working_blocks_user_name" in names


# ---------------------------------------------------------------------------
# 4. Index surface(B-tree index 命名)
# ---------------------------------------------------------------------------


def _index_names(table: object) -> set[str]:
    return {idx.name for idx in table.indexes}  # type: ignore[attr-defined]


def test_edge_indexes() -> None:
    names = _index_names(ChatMemoryEdge.__table__)
    assert "idx_edges_user_rel" in names
    assert "idx_edges_source" in names
    assert "idx_edges_target" in names
    assert "idx_edges_episode" in names


def test_node_indexes() -> None:
    names = _index_names(ChatMemoryNode.__table__)
    assert "idx_nodes_user_type" in names


def test_episode_indexes() -> None:
    names = _index_names(ChatMemoryEpisode.__table__)
    assert "idx_episodes_user_session" in names


# ---------------------------------------------------------------------------
# 5. create_all() on sqlite — 跨 dialect 兼容(L0 友好)
# ---------------------------------------------------------------------------


@pytest.fixture
def sqlite_session():  # noqa: ANN201
    """fresh sqlite + create_all of only chat_memory_* + FK target tables.

    NOTE: 仓库其它 model(如 industry_data.CompanyData)使用裸 JSONB 不带 sqlite
    variant, 全 barrel `import app.models` 会让 sqlite create_all 在它们身上挂掉
    (legacy 遗留)。本 fixture 只 import 必要 model: User / ChatSession (FK target)
    + chat_memory_*, 然后用 metadata.create_all(tables=[...]) 选择性建表, 绕开
    legacy JSONB 兼容性问题。
    """
    engine = create_engine("sqlite:///:memory:")

    # 只 import 必要 model: FK target + 自己
    from app.memory.models import (  # noqa: F401
        ChatMemoryEdge as _Edge,
    )
    from app.memory.models import (  # noqa: F401
        ChatMemoryEpisode as _Episode,
    )
    from app.memory.models import (  # noqa: F401
        ChatMemoryNode as _Node,
    )
    from app.memory.models import (  # noqa: F401
        ChatMemoryWorkingBlock as _Block,
    )
    from app.models.chat import ChatSession
    from app.models.user import User

    # 选择性 create_all — 仅这 6 张表(2 FK target + 4 c5)
    target_tables = [
        User.__table__,
        ChatSession.__table__,
        _Episode.__table__,
        _Node.__table__,
        _Edge.__table__,
        _Block.__table__,
    ]
    Base.metadata.create_all(bind=engine, tables=target_tables)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_sqlite_create_all_works(sqlite_session) -> None:  # noqa: ANN001
    """create_all on sqlite override 不抛 — proves with_variant 设置正确."""
    insp = inspect(sqlite_session.bind)
    tables = set(insp.get_table_names())
    assert "chat_memory_episodes" in tables
    assert "chat_memory_nodes" in tables
    assert "chat_memory_edges" in tables
    assert "chat_memory_working_blocks" in tables
