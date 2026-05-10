"""L1 verify Milvus chat_memory_edge_embeddings_v1 + alias 模式."""

from __future__ import annotations

import os
from typing import Any

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_MILVUS_TESTS") == "1",
    reason="Milvus container required",
)


def test_collection_exists_under_versioned_name(  # noqa: ANN001
    milvus_memory_fixture: dict[str, Any],
) -> None:
    """真实 collection 名是 chat_memory_edge_embeddings_v1(带版本后缀)."""
    from pymilvus import MilvusClient

    client = MilvusClient(
        uri=f"http://{milvus_memory_fixture['host']}:{milvus_memory_fixture['port']}"
    )
    assert client.has_collection("chat_memory_edge_embeddings_v1")


def test_alias_points_to_v1(milvus_memory_fixture: dict[str, Any]) -> None:
    """alias chat_memory_edge_embeddings_current → chat_memory_edge_embeddings_v1."""
    from pymilvus import MilvusClient

    client = MilvusClient(
        uri=f"http://{milvus_memory_fixture['host']}:{milvus_memory_fixture['port']}"
    )
    aliases = client.list_aliases(collection_name="chat_memory_edge_embeddings_v1")
    # list_aliases 返回 dict 含 'aliases' key
    alias_list = aliases.get("aliases", []) if isinstance(aliases, dict) else aliases
    assert "chat_memory_edge_embeddings_current" in alias_list


def test_schema_has_required_fields(milvus_memory_fixture: dict[str, Any]) -> None:
    """schema: edge_id Int64 PK / user_id VarChar / embedding FloatVector(1024) / rel_type VarChar."""
    from pymilvus import MilvusClient

    client = MilvusClient(
        uri=f"http://{milvus_memory_fixture['host']}:{milvus_memory_fixture['port']}"
    )
    desc = client.describe_collection(collection_name="chat_memory_edge_embeddings_v1")
    field_names = {f["name"]: f for f in desc["fields"]}
    assert "edge_id" in field_names
    assert "user_id" in field_names
    assert "embedding" in field_names
    assert "rel_type" in field_names

    # embedding dim == 1024
    emb_field = field_names["embedding"]
    assert emb_field.get("params", {}).get("dim") == 1024


def test_can_insert_and_search_via_alias(milvus_memory_fixture: dict[str, Any]) -> None:
    """通过 alias 名写入 + 检索 — 确认 alias 完全等价 collection."""
    from pymilvus import MilvusClient

    client = MilvusClient(
        uri=f"http://{milvus_memory_fixture['host']}:{milvus_memory_fixture['port']}"
    )

    alias = "chat_memory_edge_embeddings_current"
    # insert via alias
    vec = [0.1] * 1024
    rows = [
        {
            "edge_id": 999001,
            "user_id": "test-user-1",
            "embedding": vec,
            "rel_type": "HOLDS",
        }
    ]
    client.insert(collection_name=alias, data=rows)
    client.flush(alias)

    # search via alias
    results = client.search(
        collection_name=alias,
        data=[vec],
        anns_field="embedding",
        limit=1,
        output_fields=["edge_id", "rel_type"],
    )
    assert len(results) == 1
    assert results[0][0]["entity"]["edge_id"] == 999001

    # 清理
    client.delete(collection_name=alias, filter="edge_id == 999001")
