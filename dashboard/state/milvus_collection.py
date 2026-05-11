"""Harness Board DeepCard Milvus collection — spec § 6.2。

新 collection `harness_board_deepcards`(不复用 KB 的 kb_research/financial/policy)。
embedding source = name_cn + what + why + tradeoff(空字段跳过)。
"""

from __future__ import annotations

import logging
from typing import Any

from pymilvus import (
    Collection,
    CollectionSchema,
    DataType,
    FieldSchema,
    connections,
    utility,
)

from dashboard.derive.deep_card_types import DeepCard

logger = logging.getLogger(__name__)

COLLECTION_NAME = "harness_board_deepcards"
EMBEDDING_DIM = 1024  # qwen text-embedding-v3


def embedding_text(card: DeepCard, *, name_cn: str) -> str:
    """组合 name + what + why + tradeoff 作为 embedding source。spec § 6.2。

    空字段跳过(不产生连续空行)。
    """
    parts = [name_cn]
    for f in ("what", "why", "tradeoff"):
        v = getattr(card, f, None)
        if v:
            parts.append(v)
    return "\n\n".join(parts)


def _schema() -> CollectionSchema:
    return CollectionSchema(
        fields=[
            FieldSchema(name="cap_id", dtype=DataType.VARCHAR, max_length=64, is_primary=True),
            FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=EMBEDDING_DIM),
            FieldSchema(name="dimension", dtype=DataType.VARCHAR, max_length=32),
            FieldSchema(name="name_cn", dtype=DataType.VARCHAR, max_length=128),
            FieldSchema(name="status", dtype=DataType.VARCHAR, max_length=16),
            FieldSchema(name="confidence", dtype=DataType.INT8),
        ],
        description="Harness Board DeepCard embeddings",
    )


class DeepCardMilvusClient:
    """Wrap pymilvus 操作。fallback 行为在调用层处理。"""

    def __init__(self, *, host: str, port: int) -> None:
        self._alias = "harness_board"
        connections.connect(alias=self._alias, host=host, port=port)

    async def ensure_collection(self) -> None:
        if utility.has_collection(COLLECTION_NAME, using=self._alias):
            coll = Collection(COLLECTION_NAME, using=self._alias)
            coll.load()
            return
        coll = Collection(name=COLLECTION_NAME, schema=_schema(), using=self._alias)
        coll.create_index(
            field_name="embedding",
            index_params={"index_type": "AUTOINDEX", "metric_type": "COSINE"},
        )
        coll.load()

    async def upsert(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        coll = Collection(COLLECTION_NAME, using=self._alias)
        coll.upsert(
            data=[
                [r["cap_id"] for r in rows],
                [r["embedding"] for r in rows],
                [r["dimension"] for r in rows],
                [r["name_cn"] for r in rows],
                [r["status"] for r in rows],
                [r["confidence"] for r in rows],
            ]
        )
        coll.flush()

    async def search(self, vec: list[float], *, top_k: int = 5) -> list[dict[str, Any]]:
        coll = Collection(COLLECTION_NAME, using=self._alias)
        res = coll.search(
            data=[vec],
            anns_field="embedding",
            param={"metric_type": "COSINE", "params": {"ef": 64}},
            limit=top_k,
            output_fields=["cap_id", "dimension", "name_cn", "status", "confidence"],
        )
        out: list[dict[str, Any]] = []
        for hits in res:
            for hit in hits:
                out.append(
                    {
                        "cap_id": hit.entity.get("cap_id"),
                        "dimension": hit.entity.get("dimension"),
                        "name_cn": hit.entity.get("name_cn"),
                        "status": hit.entity.get("status"),
                        "confidence": hit.entity.get("confidence"),
                        "score": hit.score,
                    }
                )
        return out

    async def delete(self, cap_id: str) -> None:
        coll = Collection(COLLECTION_NAME, using=self._alias)
        coll.delete(expr=f'cap_id == "{cap_id}"')
