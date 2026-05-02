"""MilvusClient wrapper + 3 collection schema constants."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from pymilvus import CollectionSchema, DataType, FieldSchema, MilvusClient

COLLECTION_RESEARCH = "kb_research"
COLLECTION_FINANCIAL = "kb_financial"
COLLECTION_POLICY = "kb_policy"

EMBEDDING_DIM = 1024  # qwen text-embedding-v3(Spike 5 实测限制)


def _common_fields() -> list[FieldSchema]:
    return [
        FieldSchema("chunk_id", DataType.VARCHAR, max_length=80, is_primary=True),
        FieldSchema("doc_id", DataType.VARCHAR, max_length=64),
        FieldSchema("chunk_index", DataType.INT64),
        FieldSchema("chunk_text", DataType.VARCHAR, max_length=5000),
        FieldSchema("vector", DataType.FLOAT_VECTOR, dim=EMBEDDING_DIM),
        FieldSchema("pub_date", DataType.VARCHAR, max_length=10),
        FieldSchema("source_url", DataType.VARCHAR, max_length=500),
        FieldSchema("source_type", DataType.VARCHAR, max_length=20),
    ]


def schema_for(collection_name: str) -> CollectionSchema:
    """Build CollectionSchema with fields specific to the collection."""
    fields = _common_fields()

    if collection_name == COLLECTION_RESEARCH:
        fields.extend(
            [
                FieldSchema("broker", DataType.VARCHAR, max_length=50),
                FieldSchema("industry", DataType.VARCHAR, max_length=50),
                FieldSchema("rating", DataType.VARCHAR, max_length=20),
                FieldSchema("target_price", DataType.FLOAT),
                FieldSchema("analyst", DataType.VARCHAR, max_length=100),
            ]
        )
    elif collection_name == COLLECTION_FINANCIAL:
        fields.extend(
            [
                FieldSchema("company_code", DataType.VARCHAR, max_length=10),
                FieldSchema("company_name", DataType.VARCHAR, max_length=100),
                FieldSchema("fiscal_year", DataType.INT64),
                FieldSchema("fiscal_quarter", DataType.VARCHAR, max_length=4),
                FieldSchema("section", DataType.VARCHAR, max_length=50),
            ]
        )
    elif collection_name == COLLECTION_POLICY:
        fields.extend(
            [
                FieldSchema("issuer", DataType.VARCHAR, max_length=50),
                FieldSchema("doc_number", DataType.VARCHAR, max_length=50),
                FieldSchema("scope", DataType.VARCHAR, max_length=100),
            ]
        )
    else:
        raise ValueError(f"Unknown collection: {collection_name!r}")

    return CollectionSchema(
        fields=fields,
        description=f"v0.7 KB collection: {collection_name}",
    )


class MilvusKbClient:
    """Async wrapper around pymilvus.MilvusClient.

    管理 3 个 collection 的 lifecycle(ensure / insert / search / drop)。
    所有 sync pymilvus 方法用 asyncio.to_thread 包成 async。
    """

    def __init__(self, *, host: str, port: int) -> None:
        self._uri = f"http://{host}:{port}"
        self._client: Any = MilvusClient(uri=self._uri)

    async def ensure_collections(self) -> None:
        """Create collections + HNSW index if missing; load all collections."""
        for name in (COLLECTION_RESEARCH, COLLECTION_FINANCIAL, COLLECTION_POLICY):
            exists = await asyncio.to_thread(self._client.has_collection, name)
            if not exists:
                schema = schema_for(name)
                await asyncio.to_thread(
                    self._client.create_collection,
                    collection_name=name,
                    schema=schema,
                )
                # HNSW index on vector field
                index_params = MilvusClient.prepare_index_params()
                index_params.add_index(
                    field_name="vector",
                    index_type="HNSW",
                    metric_type="COSINE",
                    params={"M": 16, "efConstruction": 200},
                )
                await asyncio.to_thread(
                    self._client.create_index,
                    collection_name=name,
                    index_params=index_params,
                )
            # 每次 ensure 都 load(幂等:已 load 不报错)
            await asyncio.to_thread(
                self._client.load_collection,
                collection_name=name,
            )

    async def insert(self, collection_name: str, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        await asyncio.to_thread(
            self._client.insert,
            collection_name=collection_name,
            data=rows,
        )

    async def search(
        self,
        collection_name: str,
        *,
        query_vector: list[float],
        top_k: int,
        expr: str | None,
        output_fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Single-collection vector search;返回扁平化的命中列表."""
        results = await asyncio.to_thread(
            self._client.search,
            collection_name=collection_name,
            data=[query_vector],
            limit=top_k,
            filter=expr or "",
            output_fields=output_fields or ["*"],
        )
        # pymilvus search 返回 list[list[dict]]:外层 = 每个 query,内层 = 命中
        if not results:
            return []
        flat = []
        for hit in results[0]:
            entity = hit.get("entity", {})
            flat.append({**entity, "distance": hit.get("distance", 0.0)})
        return flat

    async def drop_all(self) -> None:
        """Test cleanup helper:drop 全部 3 collection."""
        for name in (COLLECTION_RESEARCH, COLLECTION_FINANCIAL, COLLECTION_POLICY):
            with contextlib.suppress(Exception):
                await asyncio.to_thread(self._client.drop_collection, name)
