"""L1 verify SQL migration 应用结果: partial index / GIN tsvector / GENERATED column 都能用."""

from __future__ import annotations

import os
import uuid
from typing import Any

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_PG_TESTS") == "1",
    reason="PG container required",
)


def test_partial_index_for_unextracted_episodes_exists(  # noqa: ANN001
    pg_memory_fixture: dict[str, Any],
) -> None:
    """idx_episodes_unextracted partial index 在 pg_indexes 里能查到."""
    engine = pg_memory_fixture["engine"]
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT indexname FROM pg_indexes "
                "WHERE tablename = 'chat_memory_episodes' "
                "AND indexname = 'idx_episodes_unextracted'"
            )
        ).fetchall()
    assert len(rows) == 1


def test_partial_index_for_current_snapshot_exists(  # noqa: ANN001
    pg_memory_fixture: dict[str, Any],
) -> None:
    """idx_edges_current_snapshot 是 partial WHERE valid_to IS NULL AND invalidated_at IS NULL."""
    engine = pg_memory_fixture["engine"]
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE tablename = 'chat_memory_edges' "
                "AND indexname = 'idx_edges_current_snapshot'"
            )
        ).fetchall()
    assert len(rows) == 1
    indexdef = rows[0][0]
    assert "valid_to IS NULL" in indexdef
    assert "invalidated_at IS NULL" in indexdef


def test_valid_range_index_exists(pg_memory_fixture: dict[str, Any]) -> None:  # noqa: ANN001
    """idx_edges_valid_range B-tree 复合索引(user_id, valid_from, valid_to) 存在."""
    engine = pg_memory_fixture["engine"]
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT indexname FROM pg_indexes "
                "WHERE tablename = 'chat_memory_edges' "
                "AND indexname = 'idx_edges_valid_range'"
            )
        ).fetchall()
    assert len(rows) == 1


def test_search_vector_generated_on_nodes(  # noqa: ANN001
    pg_memory_fixture: dict[str, Any],
) -> None:
    """nodes.search_vector 是 GENERATED ALWAYS AS to_tsvector('simple', search_tokens) STORED."""
    engine = pg_memory_fixture["engine"]
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT column_name, data_type, is_generated, generation_expression "
                "FROM information_schema.columns "
                "WHERE table_name = 'chat_memory_nodes' "
                "AND column_name = 'search_vector'"
            )
        ).fetchall()
    assert len(rows) == 1
    _col, dt, is_gen, gen_expr = rows[0]
    assert dt.lower() == "tsvector"
    assert is_gen == "ALWAYS"
    assert "search_tokens" in (gen_expr or "")


def test_gin_index_on_nodes_search_vector(  # noqa: ANN001
    pg_memory_fixture: dict[str, Any],
) -> None:
    """idx_nodes_search_gin USING GIN(search_vector)."""
    engine = pg_memory_fixture["engine"]
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE tablename = 'chat_memory_nodes' "
                "AND indexname = 'idx_nodes_search_gin'"
            )
        ).fetchall()
    assert len(rows) == 1
    assert "gin" in rows[0][0].lower()


def test_search_vector_generated_on_edges(  # noqa: ANN001
    pg_memory_fixture: dict[str, Any],
) -> None:
    engine = pg_memory_fixture["engine"]
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT column_name, is_generated FROM information_schema.columns "
                "WHERE table_name = 'chat_memory_edges' "
                "AND column_name = 'search_vector'"
            )
        ).fetchall()
    assert len(rows) == 1
    assert rows[0][1] == "ALWAYS"


def test_gin_index_on_edges_search_vector(  # noqa: ANN001
    pg_memory_fixture: dict[str, Any],
) -> None:
    engine = pg_memory_fixture["engine"]
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE tablename = 'chat_memory_edges' "
                "AND indexname = 'idx_edges_search_gin'"
            )
        ).fetchall()
    assert len(rows) == 1
    assert "gin" in rows[0][0].lower()


def test_search_vector_populated_from_search_tokens(  # noqa: ANN001
    pg_memory_fixture: dict[str, Any],
) -> None:
    """直接 INSERT search_tokens, GENERATED search_vector 自动产生."""
    engine = pg_memory_fixture["engine"]
    with engine.begin() as conn:
        node_id = str(uuid.uuid4())
        # seed a user explicitly to satisfy FK
        user_id = str(uuid.uuid4())
        suffix = user_id[:8]
        conn.execute(
            text(
                "INSERT INTO users (id, username, email, hashed_password) VALUES (:id, :u, :e, :p)"
            ),
            {
                "id": user_id,
                "u": f"u_{suffix}",
                "e": f"u_{suffix}@test.local",
                "p": "x",
            },
        )
        conn.execute(
            text(
                "INSERT INTO chat_memory_nodes "
                "(node_id, user_id, entity_type, entity_label, properties, search_tokens) "
                "VALUES (:nid, :uid, 'Stock', :label, '{}'::jsonb, '茅台 贵州 白酒')"
            ),
            {"nid": node_id, "uid": user_id, "label": f"x_{node_id[:6]}"},
        )
        # 用 GIN 检索
        rows = conn.execute(
            text(
                "SELECT node_id FROM chat_memory_nodes "
                "WHERE search_vector @@ to_tsquery('simple', '茅台') "
                "AND node_id = :nid"
            ),
            {"nid": node_id},
        ).fetchall()
        assert len(rows) == 1
