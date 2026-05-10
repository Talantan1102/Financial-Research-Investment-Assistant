"""3-way Hybrid Retriever — BM25(PG) + Vector(Milvus) + Graph(AGE on-demand).

spec § 5 完整实现. RRF fusion 在 rrf.py.

设计取舍 (Plan 3):
- sync Session pattern, 沿用 HierarchicalMemory DI(契约 § 3).
- vector_search / graph_traverse 仍 async, 因 embed_service.embed 与
  AgeExecutor.cypher 是 awaitable.
- BM25 是纯 PG sync.
- Graph traverse 不进 default search(spec § 5 决策), 由 Plan 4 archival_memory_traverse
  MCP tool 调用本函数. AGE 不可用时返空 list 不报错.
"""

from __future__ import annotations

import inspect
import logging
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.memory.registry import REL_TYPES, jieba_tokenize_for_search

logger = logging.getLogger(__name__)


class _MilvusClientLike(Protocol):
    def search(
        self,
        collection_name: str,
        data: list[list[float]],
        limit: int,
        output_fields: list[str] | None = None,
        filter: str | None = None,
    ) -> Any: ...


class _AgeExecutorLike(Protocol):
    async def cypher(
        self, graph_name: str, query: str, params: dict[str, Any] | None = None
    ) -> Any: ...


class _EmbedServiceLike(Protocol):
    def embed(self, text: str) -> Any: ...  # may return list[float] or awaitable


# ============================================================
# 路径 1: BM25 (PG GIN tsvector + jieba pre-tokenize)
# ============================================================


def bm25_search(
    session: Session,
    *,
    user_id: UUID,
    query: str,
    k: int = 10,
) -> list[dict[str, Any]]:
    """spec § 5 路径 1: PG ts_rank + plainto_tsquery + invalidated_at IS NULL filter.

    Args:
        session: sync SQLAlchemy Session.
        user_id: 多租户隔离.
        query: 用户原文 query, 内部走 jieba.cut_for_search 切词后再喂 plainto_tsquery.
        k: 返回 top-K.

    Returns:
        list of {edge_id, bm25_score, rel_type, importance, valid_from, valid_to},
        按 bm25_score 降序. 空 query / 切词后空 → [].
    """
    if not query or not query.strip():
        return []
    query_tokens = jieba_tokenize_for_search(query)
    if not query_tokens.strip():
        return []
    sql = text(
        """
        SELECT edge_id, rel_type, importance, valid_from, valid_to,
               ts_rank(search_vector, plainto_tsquery('simple', :q)) AS bm25_score
        FROM chat_memory_edges
        WHERE user_id = :uid
          AND invalidated_at IS NULL
          AND search_vector @@ plainto_tsquery('simple', :q)
        ORDER BY bm25_score DESC
        LIMIT :k
        """
    )
    result = session.execute(sql, {"q": query_tokens, "uid": str(user_id), "k": k})
    rows = result.fetchall()
    return [_row_to_dict(r) for r in rows]


# ============================================================
# 路径 2: Vector (Milvus 单 collection + PG meta join)
# ============================================================


async def vector_search(
    session: Session,
    *,
    milvus_client: _MilvusClientLike,
    embed_service: _EmbedServiceLike,
    user_id: UUID,
    query: str,
    k: int = 10,
    collection_name: str = "chat_memory_edge_embeddings",
) -> list[dict[str, Any]]:
    """spec § 5 路径 2: Milvus search → PG join meta.

    embed cache hook: Plan 5 提供 EmbedCache, 在调用方做包裹. Plan 3 直接调
    embed_service.embed.

    Returns:
        list of {edge_id, rel_type, importance, valid_from, valid_to, vector_distance},
        按 Milvus 距离升序保留(越近越前).
    """
    if not query or not query.strip():
        return []
    embed_call = embed_service.embed(query)
    if inspect.isawaitable(embed_call):
        query_vec = await embed_call
    else:
        query_vec = embed_call

    # Milvus 多租户 filter
    filter_expr = f'user_id == "{user_id}"'
    raw_results = milvus_client.search(
        collection_name=collection_name,
        data=[query_vec],
        limit=k,
        output_fields=["edge_id", "user_id"],
        filter=filter_expr,
    )
    if not raw_results or not raw_results[0]:
        return []

    edge_ids: list[str] = []
    distances: dict[str, float] = {}
    for hit in raw_results[0]:
        if isinstance(hit, dict):
            ent = hit.get("entity") or {}
            eid = ent.get("edge_id") or hit.get("id")
            dist = hit.get("distance", 0.0)
        else:
            ent = getattr(hit, "entity", None)
            eid = getattr(ent, "edge_id", None) or getattr(hit, "id", None)
            dist = getattr(hit, "distance", 0.0)
        if eid:
            sid = str(eid)
            edge_ids.append(sid)
            distances[sid] = float(dist)
    if not edge_ids:
        return []

    # PG join 拿 rel_type / importance / valid_from / valid_to
    sql = text(
        """
        SELECT edge_id, rel_type, importance, valid_from, valid_to
        FROM chat_memory_edges
        WHERE edge_id = ANY(CAST(:eids AS uuid[]))
          AND invalidated_at IS NULL
        """
    )
    rows = session.execute(sql, {"eids": edge_ids}).fetchall()
    by_id: dict[str, dict[str, Any]] = {}
    for r in rows:
        d = _row_to_dict(r)
        by_id[str(d["edge_id"])] = d
    out: list[dict[str, Any]] = []
    for eid in edge_ids:
        if eid in by_id:
            d = by_id[eid]
            d["vector_distance"] = distances[eid]
            out.append(d)
    return out


# ============================================================
# 路径 3: Graph (AGE Cypher on-demand) — 不进 default search
# ============================================================


async def graph_traverse(
    session: Session,
    *,
    age_executor: _AgeExecutorLike | None,
    user_id: UUID,
    start_label: str,
    hops: int = 2,
    rel_types: list[str] | None = None,
) -> list[dict[str, Any]]:
    """spec § 5 路径 3: AGE Cypher 多跳遍历. Plan 4 archival_memory_traverse 调用.

    On-demand, 不进 default search 因为需要 start_label 抽取(LLM call).

    Args:
        session: sync SQLAlchemy Session(reserved for future PG meta join).
        age_executor: AGE executor; None 或 cypher raise → fallback 空 list.
        start_label: 起点 entity_label, e.g. 'User' or '600519.SH'.
        hops: 1-3, 上限避免爆炸.
        rel_types: 限定 traverse 的 rel_type, None 默认全部 11 类.

    Returns:
        list of dict (AGE rows). AGE 不可用时返空 list 不报错.

    Raises:
        ValueError: hops 不在 1..3.
    """
    if not (1 <= hops <= 3):
        raise ValueError(f"hops must be 1..3, got {hops}")
    rel_types_final = rel_types if rel_types is not None else list(REL_TYPES)

    if age_executor is None:
        return []

    cypher = (
        "MATCH path = (start {entity_label: $label, user_id: $uid})"
        f"-[*1..{hops}]-(end) "
        "WHERE all(e IN relationships(path) WHERE "
        "type(e) IN $rel_types AND e.invalidated_at IS NULL) "
        "RETURN path LIMIT 20"
    )
    try:
        rows = await age_executor.cypher(
            "chat_memory",
            cypher,
            {"label": start_label, "uid": str(user_id), "rel_types": rel_types_final},
        )
    except Exception as exc:  # noqa: BLE001 — AGE absence is expected fallback
        logger.warning("graph_traverse: AGE cypher failed (fallback empty): %s", exc)
        return []

    if not rows:
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(dict(r) if not isinstance(r, dict) else r)
    return out


# ============================================================
# RRF input shaping
# ============================================================


def format_edges_meta_for_rrf(
    retriever_results: list[list[dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    """从各 retriever 结果合并 edge meta 给 rrf.reciprocal_rank_fusion_v2 用.

    Returns: {edge_id: {rel_type, importance, valid_from, valid_to}}.
    Edge 在多 retriever 出现时去重(取第一次见的元数据).
    """
    out: dict[str, dict[str, Any]] = {}
    for retr_list in retriever_results:
        for item in retr_list:
            eid = str(item["edge_id"])
            if eid not in out:
                out[eid] = {
                    "rel_type": item.get("rel_type"),
                    "importance": item.get("importance"),
                    "valid_from": item.get("valid_from"),
                    "valid_to": item.get("valid_to"),
                }
    return out


# ============================================================
# helpers
# ============================================================


def _row_to_dict(row: Any) -> dict[str, Any]:
    """SQLAlchemy Row → dict, 兼容 _mapping / 直 dict."""
    if isinstance(row, dict):
        return dict(row)
    if hasattr(row, "_mapping"):
        return dict(row._mapping)
    return dict(row)
