"""Shared helpers for memory MCP tools (Plan 4 ship).

Responsibilities:
  - HierarchicalMemory factory (lazy build from env).
  - Tool-call log writer (one row per invocation, drives spec § 6 周报 SQL).
  - Latency timer context manager.

The factory is intentionally minimal: production wiring (AGE / Milvus / real
LLM) is left to Plan 8 dogfood. Plan 4 ships a path that runs end-to-end with
mocked LLM/judge but real PG/Milvus/embed via env. Tools that strictly need
LLM (none in Plan 4 — agent calls them; LLM judge only kicks in inside
HierarchicalMemory.archival_memory_insert when there are existing edges) get
the same factory.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)

# C50: module-level lazy singleton — avoids creating a new HierarchicalMemory
# (+ MilvusClient + embedder) on every tool call. The MCP server runs as a
# long-lived stdio process; without this, connections accumulate indefinitely.
_MEMORY_INSTANCE: Any = None
_MEMORY_LOCK = threading.Lock()


def get_memory() -> Any:
    """Return the process-level HierarchicalMemory singleton.

    Double-checked locking: the instance is created once on first call and
    reused for the lifetime of the MCP server process.  Use
    ``build_memory_from_env()`` directly only when a fresh instance is needed
    (e.g. in tests that need isolated state).
    """
    global _MEMORY_INSTANCE  # noqa: PLW0603
    if _MEMORY_INSTANCE is None:  # fast-path without lock
        with _MEMORY_LOCK:
            if _MEMORY_INSTANCE is None:  # re-check under lock
                _MEMORY_INSTANCE = build_memory_from_env()
    return _MEMORY_INSTANCE


def build_memory_from_env() -> Any:
    """Construct a HierarchicalMemory using factory wiring from env.

    Returns a HierarchicalMemory; AGE / Milvus / LLM judge wiring is best-effort
    and may be `None` (HierarchicalMemory tolerates None per Plan 1B + 2A
    semantics — best-effort sync, outbox fallback, fail-safe APPEND_NEW).
    """
    import os

    from app.core.database import SessionLocal
    from app.memory.conflict_resolver import ConflictResolver
    from app.memory.extractor import LLMExtractor
    from app.memory.hierarchical import HierarchicalMemory
    from app.services.embedding_factory import build_embedding_service_from_env

    embed = build_embedding_service_from_env()

    # LLM judge / extractor are best-effort: if env can't build LLM, fall back
    # to None (HierarchicalMemory's archival_memory_insert short-circuits to
    # APPEND_NEW when there are no existing edges, so no-LLM path still writes).
    llm_judge: Any = None
    llm_extractor: Any = None
    try:
        from app.memory.llm_service_adapter import MemoryLLMClientAdapter
        from app.services.openai_client import build_llm_service_from_env

        # 2026-06-05 对话流评估冒烟发现 #3:抽取层期望 async
        # chat(prompt, system, ...) -> str 协议,直接塞 LLMService 会 TypeError 全灭。
        llm = MemoryLLMClientAdapter(build_llm_service_from_env(), tier="fast")
        llm_judge = ConflictResolver(llm_client=llm)
        llm_extractor = LLMExtractor(llm_client=llm)
    except Exception as exc:  # noqa: BLE001
        logger.warning("memory MCP: LLM unavailable, falling back to no-judge: %s", exc)

    # Milvus client (best-effort) —— 不可达时退化成 None,不阻塞调用方。
    # 坑:MilvusClient(uri=...) 在 Milvus 不可达时不抛异常,而是无限阻塞在 gRPC
    # `_wait_for_channel_ready`(pymilvus 默认无连接超时),使下面的 try/except 兜底
    # 形同虚设 —— eval/离线场景(Milvus 没起)会让 build_heavy_singletons 永久挂死。
    # 先用一个短超时 TCP 探针判活:端口未监听则立即 ECONNREFUSED → 落 except → None。
    milvus_client: Any = None
    host = os.environ.get("MILVUS_HOST", "127.0.0.1")
    port = int(os.environ.get("MILVUS_PORT", "19530"))
    try:
        import socket

        with socket.create_connection((host, port), timeout=2):
            pass
        from pymilvus import MilvusClient

        milvus_client = MilvusClient(uri=f"http://{host}:{port}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("memory MCP: Milvus unavailable (%s) — 记忆降级无向量检索", exc)

    return HierarchicalMemory(
        pg_session_factory=SessionLocal,
        age_executor=None,  # AGE wiring deferred; archival_memory_traverse falls back to []
        milvus_client=milvus_client,
        embed_service=embed,
        llm_extractor=llm_extractor,
        llm_judge=llm_judge,
    )


def build_db_session() -> Any:
    """Return a fresh sync Session from the app's SessionLocal factory.

    Each tool that needs ad-hoc DB access (e.g. archival_memory_insert's
    evidence_quote check) calls this and is responsible for closing it.
    """
    from app.core.database import SessionLocal

    return SessionLocal()


def write_tool_call_log(
    *,
    user_id: UUID | str,
    tool_name: str,
    args_json: dict[str, Any],
    result_count: int,
    latency_ms: float,
    error: str | None = None,
) -> None:
    """Append one row to mcp_tool_call_log (Plan 4 ship table).

    Best-effort: any DB error is swallowed (logger.warning) so a logging
    failure never breaks a tool invocation.
    """
    try:
        from app.core.database import SessionLocal
        from app.services.trace_models import MCPToolCallLog

        session = SessionLocal()
        try:
            log = MCPToolCallLog(
                user_id=str(user_id),
                tool_name=tool_name,
                args_json=args_json,
                result_count=result_count,
                latency_ms=latency_ms,
                error=error,
            )
            session.add(log)
            session.commit()
        finally:
            session.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("write_tool_call_log failed (tool=%s): %s", tool_name, exc)


class Timer:
    """Context manager exposing elapsed_ms after exit."""

    elapsed_ms: float

    def __enter__(self) -> Timer:
        self._start = time.perf_counter()
        self.elapsed_ms = 0.0
        return self

    def __exit__(self, *_: Any) -> None:
        self.elapsed_ms = (time.perf_counter() - self._start) * 1000


def infer_entity_types(rel_type: str, source_label: str, target_label: str) -> tuple[str, str]:
    """Heuristic mapping rel_type + label → (source_entity_type, target_entity_type).

    The MCP tool's input schema (per spec § 6 / 附录 C) is shorthand: agent
    passes only `rel_type / source_label / target_label`. Underlying
    HierarchicalMemory.archival_memory_insert needs entity types. Use a
    deterministic table:

      rel_type               source        target
      HOLDS / SOLD           User          Stock
      WATCHES / PREFERS / AVOIDS  User    Stock|Industry|Sector|Concept
      EXPRESSED_VIEW         User          (any)
      STUDIED                User          Stock|Industry
      COMPARED               Stock         Stock
      BELONGS_TO             Stock         Industry|Sector
      HAS_CONCEPT            Stock         Concept
      CORRELATED_WITH        Stock         Stock

    When source_label == "User" → source_entity_type = "User"; otherwise
    fallback Stock for source. Target side falls back to "Stock" when no
    structural hint (agents can override by passing entity types in
    content.properties.source_entity_type / target_entity_type — recognized in
    the calling tool).
    """
    rel = rel_type.upper()
    if rel in {"BELONGS_TO"}:
        return "Stock", "Industry"
    if rel in {"HAS_CONCEPT"}:
        return "Stock", "Concept"
    if rel in {"COMPARED", "CORRELATED_WITH"}:
        return "Stock", "Stock"
    # User-centric rel_types
    if source_label == "User":
        return "User", "Stock"
    return "Stock", "Stock"
