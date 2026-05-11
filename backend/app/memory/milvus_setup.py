"""Milvus collection setup for C.5 chat_memory edge embeddings.

Spec § 2 行 304-318:
    collection = "chat_memory_edge_embeddings"
    schema = {edge_id Int64, user_id VarChar(36), embedding FloatVector(1024), rel_type VarChar(32)}

Plan 1A 决策(spec § 11 末尾 #1 触发后做留口子):
    真实 collection 名带版本后缀 chat_memory_edge_embeddings_v1
    业务代码统一通过 alias chat_memory_edge_embeddings_current 引用
    向量模型升级时建 _v2 + alias 切换 — 本 plan 不实现升级流程

复用 v0.7 KB Milvus client 模式(backend/app/services/milvus_client.py):
    - HNSW index on embedding field, COSINE metric
    - load_collection 在 ensure 后调一次(spec sediment: feedback_milvus_load_after_index.md)
"""

from __future__ import annotations

import contextlib

from pymilvus import CollectionSchema, DataType, FieldSchema, MilvusClient

EMBEDDING_DIM = 1024  # qwen text-embedding-v3(契约 § 9 同)

COLLECTION_V1_NAME = "chat_memory_edge_embeddings_v1"
"""真实 collection 名(带版本后缀, 给 #1 向量模型升级 hook 留口子)."""

ALIAS_NAME = "chat_memory_edge_embeddings_current"
"""业务代码引用名 — Plan 2-5 检索 / 写入只用 alias, 升级时 alias 切换零代码改动."""


def _build_schema() -> CollectionSchema:
    """Spec § 2 行 308-313."""
    fields = [
        FieldSchema(
            "edge_id",
            DataType.INT64,
            is_primary=True,
            description="PG chat_memory_edges.edge_id",
        ),
        FieldSchema("user_id", DataType.VARCHAR, max_length=36, description="多租户隔离"),
        FieldSchema("embedding", DataType.FLOAT_VECTOR, dim=EMBEDDING_DIM),
        FieldSchema("rel_type", DataType.VARCHAR, max_length=32),
    ]
    return CollectionSchema(
        fields=fields,
        description=(
            "C.5 chat_memory edge embeddings (qwen v3 1024d). "
            "Embed text template: '{rel_type} {src_label} → {tgt_label} reasoning=...'. "
            "Plan 1A schema; Plan 2 写入; Plan 3 检索."
        ),
    )


def ensure_chat_memory_edge_collection(*, host: str, port: int) -> None:
    """幂等创建 collection v1 + HNSW index + alias.

    第一次跑: create_collection + create_index + load + create_alias
    重复跑: skip(has_collection / has_alias)
    """
    client = MilvusClient(uri=f"http://{host}:{port}")

    # 1. collection
    if not client.has_collection(COLLECTION_V1_NAME):
        schema = _build_schema()
        client.create_collection(
            collection_name=COLLECTION_V1_NAME,
            schema=schema,
        )

        # 2. HNSW index on embedding(跟 v0.7 KB 同款参数)
        index_params = MilvusClient.prepare_index_params()
        index_params.add_index(
            field_name="embedding",
            index_type="HNSW",
            metric_type="COSINE",
            params={"M": 16, "efConstruction": 200},
        )
        client.create_index(
            collection_name=COLLECTION_V1_NAME,
            index_params=index_params,
        )

    # 3. load collection(必须在 create_index 之后, sediment: feedback_milvus_load_after_index.md)
    client.load_collection(COLLECTION_V1_NAME)

    # 4. alias(幂等: alter_alias 把已有 alias 重新指向, 不存在则 create)
    try:
        existing_aliases = client.list_aliases(collection_name=COLLECTION_V1_NAME)
        alias_list = (
            existing_aliases.get("aliases", [])
            if isinstance(existing_aliases, dict)
            else existing_aliases
        )
        if ALIAS_NAME not in alias_list:
            client.create_alias(
                collection_name=COLLECTION_V1_NAME,
                alias=ALIAS_NAME,
            )
    except Exception:
        # 兜底: list_aliases / create_alias API 在不同 pymilvus 版本签名有差异
        # alias 已存在时静默 skip
        with contextlib.suppress(Exception):
            client.create_alias(
                collection_name=COLLECTION_V1_NAME,
                alias=ALIAS_NAME,
            )
