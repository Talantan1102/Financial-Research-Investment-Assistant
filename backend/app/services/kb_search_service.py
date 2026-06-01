"""KbSearchService Protocol + KbHit model + MilvusKbSearchService impl."""

from __future__ import annotations

import asyncio
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from app.services.embedding_service import EmbeddingService
from app.services.milvus_client import (
    COLLECTION_FINANCIAL,
    COLLECTION_POLICY,
    COLLECTION_RESEARCH,
    MilvusKbClient,
)

_ALL_COLLECTIONS = (COLLECTION_RESEARCH, COLLECTION_FINANCIAL, COLLECTION_POLICY)


# Filter 字段白名单(spec 节 5 锁死)
_COMMON_FILTER_FIELDS = {"pub_date_after", "pub_date_before", "source_type"}
_COLLECTION_FILTER_FIELDS: dict[str, set[str]] = {
    COLLECTION_RESEARCH: {"broker", "industry", "rating", "analyst"},
    COLLECTION_FINANCIAL: {"company_code", "fiscal_year", "fiscal_quarter", "section"},
    COLLECTION_POLICY: {"issuer", "scope"},
}


class KbHit(BaseModel):
    chunk_id: str
    chunk_text: str
    similarity: float  # 余弦相似度([-1,1],越大越相似;Milvus COSINE 的 distance 即此值)
    metadata: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class KbSearchService(Protocol):
    async def search(
        self,
        query: str,
        collections: list[str] | None = None,
        top_k: int = 5,
        threshold: float | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[KbHit]: ...


class MilvusKbSearchService:
    """Real Milvus-backed KbSearchService.

    流程:embed query → 多 collection 并查 → 合并 → threshold 过滤 → 按 similarity 降序 → top_k 截断。
    """

    def __init__(
        self,
        *,
        milvus: MilvusKbClient,
        embedding_service: EmbeddingService,
    ) -> None:
        self._milvus = milvus
        self._embedding = embedding_service

    async def search(
        self,
        query: str,
        collections: list[str] | None = None,
        top_k: int = 5,
        threshold: float | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[KbHit]:
        target = list(collections) if collections else list(_ALL_COLLECTIONS)
        for c in target:
            if c not in _ALL_COLLECTIONS:
                raise ValueError(f"Unknown collection: {c!r}")

        # filter 字段白名单 verify
        if filters:
            allowed = _COMMON_FILTER_FIELDS | {
                f for c in target for f in _COLLECTION_FILTER_FIELDS.get(c, set())
            }
            for field in filters:
                if field not in allowed:
                    raise ValueError(f"Filter field {field!r} not in filter whitelist for {target}")

        embeddings = await self._embedding.embed([query])
        query_vector = embeddings[0]

        results: list[KbHit] = []
        # 并发查多 collection
        tasks = [self._search_one(c, query_vector, top_k, filters) for c in target]
        per_collection = await asyncio.gather(*tasks)
        for hits in per_collection:
            results.extend(hits)

        # threshold 过滤
        if threshold is not None:
            results = [h for h in results if h.similarity >= threshold]

        # 按 similarity 降序排,top_k 截断
        results.sort(key=lambda h: h.similarity, reverse=True)
        return results[:top_k]

    async def _search_one(
        self,
        collection: str,
        query_vector: list[float],
        top_k: int,
        filters: dict[str, Any] | None,
    ) -> list[KbHit]:
        expr = self._build_expr(collection, filters)
        rows = await self._milvus.search(
            collection,
            query_vector=query_vector,
            top_k=top_k,
            expr=expr,
        )
        out: list[KbHit] = []
        for row in rows:
            distance = float(row.pop("distance", 0.0))
            # Milvus COSINE 度量下,search 返回的 distance 字段**本身就是余弦相似度**
            # ([-1,1],越大越相似),不是 L2 那种"越小越近"的距离。原实现
            # `max(0.0, 1.0 - distance)` 把方向彻底搞反(完全相同向量 cos=1 → 0.0 当最差,
            # 正交 cos=0 → 1.0 当最好),导致 sort(reverse=True) 返回**最不相关**的 chunk、
            # threshold 过滤方向也反。直接用 distance 即正确的相似度。
            similarity = distance
            chunk_id = str(row.pop("chunk_id", ""))
            chunk_text = str(row.pop("chunk_text", ""))
            out.append(
                KbHit(
                    chunk_id=chunk_id,
                    chunk_text=chunk_text,
                    similarity=similarity,
                    metadata=row,
                )
            )
        return out

    @staticmethod
    def _build_expr(collection: str, filters: dict[str, Any] | None) -> str | None:
        if not filters:
            return None
        parts: list[str] = []
        for k, v in filters.items():
            if k == "pub_date_after":
                parts.append(f'pub_date >= "{v}"')
            elif k == "pub_date_before":
                parts.append(f'pub_date <= "{v}"')
            elif isinstance(v, str):
                parts.append(f'{k} == "{v}"')
            elif isinstance(v, (int, float)):
                parts.append(f"{k} == {v}")
            else:
                raise ValueError(f"Unsupported filter value type for {k}: {type(v).__name__}")
        return " and ".join(parts)
