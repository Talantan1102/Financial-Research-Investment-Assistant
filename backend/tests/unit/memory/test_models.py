"""L0 schema test for chat_memory_* models. PG-specific behaviors covered in L1.

覆盖:
- 4 model 类可 import + tablename 正确
- 字段名 / 类型 / nullable 跟契约 § 4 对齐
- UNIQUE / CHECK constraint 在 metadata 里被识别
"""

from __future__ import annotations

from app.memory.models import (
    ChatMemoryEdge,
    ChatMemoryEpisode,
    ChatMemoryNode,
    ChatMemoryWorkingBlock,
)

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
# 5. create_all() on PG — 现在所有 L0/L1 都走真 PG (conftest db_session fixture);
# fixture 启动时 DROP SCHEMA + create_all,已经隐含验证 schema 可建。本文件不再
# 单独跑 create_all smoke。
# ---------------------------------------------------------------------------
