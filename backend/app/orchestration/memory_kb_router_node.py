"""LangGraph node — Memory vs KB Search 检索路由 + 并行检索。

Topology placement(chat_graph.py):
    context_node → memory_kb_router_node → planner_node → ...

Responsibility:
    1. 调 router_fn(state.user_message) → RouterDecision
    2. 按 retrieval_targets 并行检索 memory.archival_memory_search 和 / 或 kb.search
    3. graceful degrade: 单路 fail 不 kill 另一路(both 模式)
    4. update ChatState 4 fields

per spec § 11 末尾 #7 (a)(c).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from app.agents.schemas import ChatState
from app.memory.memory_kb_router import RouterDecision
from app.services.kb_search_service import KbHit, KbSearchService

logger = logging.getLogger(__name__)

RouterFn = Callable[[str], Awaitable[RouterDecision]]

_ANONYMOUS_UUID = UUID("00000000-0000-0000-0000-000000000000")


def _serialize_memory_edge(edge: Any) -> dict[str, Any]:
    """Convert ChatMemoryEdge or compatible mock into a JSON-friendly dict.

    LangGraph state checkpointer needs JSON-serializable values; ChatMemoryEdge
    SQLAlchemy ORM instances are not, so we project to plain dicts here.
    """
    valid_from = getattr(edge, "valid_from", None)
    return {
        "edge_id": str(getattr(edge, "edge_id", "")),
        "rel_type": getattr(edge, "rel_type", None),
        "properties": dict(getattr(edge, "properties", {}) or {}),
        "source_node_id": str(getattr(edge, "source_node_id", "")),
        "target_node_id": str(getattr(edge, "target_node_id", "")),
        "importance": getattr(edge, "importance", None),
        "valid_from": str(valid_from) if valid_from is not None else None,
        "reasoning": getattr(edge, "reasoning", None),
    }


def _serialize_kb_hit(hit: Any) -> dict[str, Any]:
    if isinstance(hit, KbHit):
        return hit.model_dump()
    return {
        "chunk_id": getattr(hit, "chunk_id", ""),
        "chunk_text": getattr(hit, "chunk_text", ""),
        "similarity": getattr(hit, "similarity", 0.0),
        "metadata": dict(getattr(hit, "metadata", {}) or {}),
    }


async def _safe_memory_search(memory: Any, user_id: UUID, query: str) -> list[dict[str, Any]]:
    try:
        edges = await memory.archival_memory_search(user_id=user_id, query=query, k=5)
    except Exception as e:  # noqa: BLE001 — graceful degrade, single-path fail
        logger.warning("memory_kb_router_node memory search failed: %s — graceful degrade", e)
        return []
    return [_serialize_memory_edge(e) for e in (edges or [])]


async def _safe_kb_search(kb: KbSearchService, query: str) -> list[dict[str, Any]]:
    try:
        hits = await kb.search(query=query, top_k=5)
    except Exception as e:  # noqa: BLE001 — graceful degrade, single-path fail
        logger.warning("memory_kb_router_node kb search failed: %s — graceful degrade", e)
        return []
    return [_serialize_kb_hit(h) for h in (hits or [])]


async def memory_kb_router_node(
    state: ChatState,
    *,
    memory: Any,  # HierarchicalMemory or InSessionMemory(stub)
    kb: KbSearchService,
    router_fn: RouterFn,
) -> dict[str, Any]:
    """Run routing decision + parallel retrieval; emit state update dict.

    Returns dict subset of ChatState fields(LangGraph state-update protocol).

    Args:
        state: current ChatState (user_message used as query)
        memory: object with ``archival_memory_search(user_id, query, k)`` async method
        kb: KbSearchService (Protocol)
        router_fn: async callable ``str -> RouterDecision``

    Returns:
        dict with 4 fields: retrieval_targets / memory_hits / kb_hits /
        memory_kb_routing_reasoning
    """
    decision = await router_fn(state.user_message)
    target = decision.retrieval_targets[0]  # single-element by RouterDecision contract

    # Resolve user_id → UUID. Legacy / anonymous strings get the all-zero UUID;
    # downstream memory layer 自行决定怎么处理(可能拒,也可能空返)。
    user_uuid: UUID
    try:
        user_uuid = UUID(state.user_id)
    except (ValueError, AttributeError, TypeError):
        user_uuid = _ANONYMOUS_UUID

    memory_hits: list[dict[str, Any]]
    kb_hits: list[dict[str, Any]]

    if target == "memory":
        memory_hits = await _safe_memory_search(memory, user_uuid, state.user_message)
        kb_hits = []
    elif target == "kb":
        memory_hits = []
        kb_hits = await _safe_kb_search(kb, state.user_message)
    else:  # "both"
        memory_hits, kb_hits = await asyncio.gather(
            _safe_memory_search(memory, user_uuid, state.user_message),
            _safe_kb_search(kb, state.user_message),
        )

    return {
        "retrieval_targets": list(decision.retrieval_targets),
        "memory_hits": memory_hits,
        "kb_hits": kb_hits,
        "memory_kb_routing_reasoning": decision.reasoning,
    }
