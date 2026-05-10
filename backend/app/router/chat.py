"""HTTP POST /api/v0/chat — SSE streaming chat endpoint.

Wires together:
- ChatRequest / StreamEvent Pydantic models (per spec § 5 / § 4.6)
- get_chat_graph() DI: lazy singleton CompiledStateGraph
- get_current_user() DI: v0 stub (anonymous) — real auth preserved in auth_router
- _stream_chat(): async generator over LangGraph astream_events → SSE frames
- _adapt_event(): maps LangGraph event types to StreamEvent types per spec § 4.6

Event mapping (from Spike 2 probe; confirmed against real astream_events output):
  on_chain_end / planner_node     → plan
  on_chain_start / tool_node      → tool_start
  on_chain_end / tool_node        → tool_end
  on_chain_end / LangGraph        → done  (top-level graph end)
  on_chat_model_stream             → token (v0 Responder uses sync chat; may not appear)
  all other events                → None (skipped)
  any unhandled exception          → error (best-effort, stream continues)

Escalation events (Plan 3 — emitted after main stream when planner.escalate_offered):
  escalate_request      → emitted immediately if final_state.escalate_offered
  escalate_packet_draft → emitted after EscalationExtractor.run() + repo.create_draft()

StreamEvent.seq is a monotonic per-stream counter starting at 1, used for
last_event_id-based SSE reconnect (spec § 4.6 / G1 industrial problem).
"""

from __future__ import annotations

import logging
import traceback
from collections.abc import AsyncIterator
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel

from app.agents.escalation_extractor import EscalationExtractor
from app.agents.schemas import GraphState
from app.services.escalation_record_repo import EscalationRecordRepo

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat-v0"])

# ---------------------------------------------------------------------------
# Escalation dependency stubs (Plan 3 E2 — wired by app_main lifespan in T11)
# ---------------------------------------------------------------------------


def get_escalation_extractor() -> EscalationExtractor:
    """Return an EscalationExtractor instance.

    Replaced via ``dependency_overrides`` in tests and by app_main lifespan in
    Task 11 (which wires the real LLMService).  Raising here acts as a safe
    sentinel: any request that reaches escalation without a proper override will
    fail loudly rather than silently skip extraction.
    """
    raise RuntimeError("EscalationExtractor dependency not configured")


def get_escalation_record_repo() -> EscalationRecordRepo:
    """Return an EscalationRecordRepo instance.

    Replaced via ``dependency_overrides`` in tests and by app_main lifespan in
    Task 11 (which wires the real async DB session factory).
    """
    raise RuntimeError("EscalationRecordRepo dependency not configured")


# ---------------------------------------------------------------------------
# Request / Response schemas (spec § 5)
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    session_id: str  # client-generated UUID; cross-turn session identifier
    message: str
    enable_web_search: bool = False  # v0 placeholder
    enable_kb_search: bool = False  # v0 placeholder


class StreamEvent(BaseModel):
    """SSE event shape per spec § 4.6.

    `seq` is a monotonic counter scoped to the chat stream, used for
    last_event_id-based reconnect (G1 industrial problem).  It starts at 1
    and increments by 1 for every emitted event in a single stream.
    """

    type: Literal[
        # chat-mode events
        "token",
        "plan",
        "tool_start",
        "tool_end",
        "tool_error",
        "skill_load",  # Plan 2 emits
        "escalate_request",
        "escalate_packet_draft",  # Plan 3 emits
        # research-subgraph events (Plan 3 forwards from research mode)
        "research_planner_done",
        "research_tool_start",
        "research_tool_end",
        "research_analyst_done",
        "research_writer_done",
        "research_critic_done",
        "escalate_done",
        "escalate_error",
        # cross-cutting
        "cost_update",
        "done",
        "error",
        # Plan 2b NEW — L3b script execution
        "skill_execute_start",
        "skill_execute_end",
        "skill_execute_error",
    ]
    seq: int  # monotonic; starts at 1, increments per emit per stream
    data: dict[str, Any]


# ---------------------------------------------------------------------------
# Stub User — v0 anonymous auth (real JWT auth lives in auth_router)
# ---------------------------------------------------------------------------


class _AnonUser:
    """Minimal user object for v0 anonymous access."""

    id: str = "anonymous"

    def __init__(self) -> None:
        self.id = "anonymous"


def get_current_user() -> _AnonUser:
    """v0 stub: every request is treated as anonymous.

    Real auth is preserved in app.router.auth_router (OAuth2 + JWT).  This
    stub is replaced by a proper dependency once auth integration is wired
    into the new router in a future task.
    """
    return _AnonUser()


# ---------------------------------------------------------------------------
# Singleton graph — built once at first request, reused across requests
# ---------------------------------------------------------------------------

_graph_singleton: CompiledStateGraph[Any, Any, Any, Any] | None = None


def _build_async_pg_session_factory_or_none() -> Any | None:
    """Build sync session factory from env DATABASE_URL.

    无 PG / 测试环境返回 None, fallback 走 InSessionMemory(保 Q4 E 兼容).
    """
    import os

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        return None
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session, sessionmaker

        engine = create_engine(db_url, pool_pre_ping=True)
        Factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)

        def _factory() -> Session:
            return Factory()

        return _factory
    except Exception as e:
        logger.warning("DI fallback to InSessionMemory: %s", e)
        return None


def _build_graph_singleton(
    checkpointer: Any | None = None,
) -> CompiledStateGraph[Any, Any, Any, Any]:
    """Build the CompiledStateGraph once and cache it as a module-level singleton.

    Build sequence:
    1. build_llm_service_from_env()  — real LLMService (LLM_MODE drives
       which client is used at env-var dispatch time, not here).
    2. build_tushare_service()        — mock or real per TUSHARE_MODE env var
    3. MockBochaService()            — reads LLMConfig internally
    4. Register StockQuoteTool / GetFinancialsTool / GetNewsTool (legacy 3-tool set)
       MCP-based tools (6 total) are registered via MCPClient tools in Plan 2.
    5. ChatPlanner + Responder
    6. InSessionMemory (Q4 E: tool dedup + token-guard)
    7. ToolResultCache (placeholder — no async_engine at singleton build time; cache is
       None-ish until ChatSessionRepo async_engine is wired in Plan 2)
    8. build_chat_graph with PG checkpointer from app.state (or None for tests)

    Thread safety: FastAPI runs in a single async event loop for the
    startup sequence; the singleton is set before requests arrive.
    For multi-worker deployments the per-worker singleton is acceptable
    since LangGraph state isolation is provided by thread_id, not process.
    """
    from app.agents.chat_planner import ChatPlanner
    from app.agents.in_session_memory import InSessionMemory
    from app.agents.responder import Responder
    from app.memory.hierarchical import HierarchicalMemory
    from app.orchestration.chat_graph import build_chat_graph
    from app.services.bocha_factory import build_bocha_service_from_env
    from app.services.openai_client import build_llm_service_from_env
    from app.services.tushare_factory import build_tushare_service
    from app.tools.get_financials import GetFinancialsTool
    from app.tools.get_news import GetNewsTool
    from app.tools.get_stock_quote import StockQuoteTool
    from app.tools.registry import ToolRegistry

    llm = build_llm_service_from_env()
    tushare = build_tushare_service()

    registry = ToolRegistry()
    registry.register(StockQuoteTool(tushare=tushare))
    registry.register(GetFinancialsTool(tushare=tushare))
    registry.register(GetNewsTool(bocha=build_bocha_service_from_env()))

    planner = ChatPlanner(llm=llm, registry=registry)
    responder = Responder(llm=llm)

    # C.5 Plan 1B: HierarchicalMemory 替换 InSessionMemory 作为主 Memory Protocol 实现.
    # InSessionMemory 仍可用于 in-session dedup / token-guard summarize(Q4 E),
    # 但 cross-session memory 方法走 HierarchicalMemory.
    # Plan 2-4 的 archival_memory_* 方法 ship 后, 此处真 inject embed_service / llm_extractor;
    # Plan 1B 阶段 Plan 2-4 stub 方法 raise NotImplementedError, agent 调到时报错(预期).
    pg_factory = _build_async_pg_session_factory_or_none()
    memory: Any
    if pg_factory is None:
        # 测试 / 无 PG 环境: fallback InSessionMemory 保 Q4 E behavior
        memory = InSessionMemory(llm=llm)
    else:
        memory = HierarchicalMemory(
            pg_session_factory=pg_factory,
            age_executor=None,  # Plan 2 inject
            milvus_client=None,  # Plan 2 inject
            embed_service=None,  # Plan 2 inject
            llm_extractor=None,  # Plan 2 inject
            llm_judge=None,  # Plan 2 inject
        )

    # ToolResultCache requires async session factory; deferred to Plan 2 when
    # ChatSessionRepo engine is wired. For now pass a no-op stub cache.
    class _NoOpCache:
        """Stub ToolResultCache that always misses (no PG async wiring at build time)."""

        async def get_or_compute(
            self,
            user_id: str,
            tool_name: str,
            args: Any,
            compute_fn: Any,
        ) -> Any:
            return await compute_fn()

    return build_chat_graph(
        planner=planner,
        responder=responder,
        registry=registry,
        memory=memory,
        cache=_NoOpCache(),  # type: ignore[arg-type]
        checkpointer=checkpointer,
    )


def get_chat_graph(request: Request) -> CompiledStateGraph[Any, Any, Any, Any]:
    """FastAPI dependency: return the module-level singleton graph.

    The PG checkpointer is read from app.state (set during lifespan) on first
    call, then the compiled graph is cached for the lifetime of the process.
    """
    global _graph_singleton
    if _graph_singleton is None:
        checkpointer = getattr(request.app.state, "chat_checkpointer", None)
        _graph_singleton = _build_graph_singleton(checkpointer=checkpointer)
    return _graph_singleton


# ---------------------------------------------------------------------------
# SSE event adapter
# ---------------------------------------------------------------------------


def _adapt_event(ev: dict[str, Any], seq: int) -> StreamEvent | None:
    """Translate a LangGraph astream_events dict into a StreamEvent or None.

    Mapping (confirmed by Spike 2 local probe; extended to spec § 4.6 types):
      on_chain_end   + planner_node  → plan       (plan decided)
      on_chain_start + tool_node     → tool_start
      on_chain_end   + tool_node     → tool_end
      on_chain_end   + LangGraph     → done       (top-level graph finished)
      on_chat_model_stream           → token      (streaming token; v0 may not emit)
      all others                     → None (skip)

    Args:
        ev:  Raw LangGraph astream_events dict.
        seq: Monotonic sequence number for this event (already incremented by caller).
    """
    ev_type: str = ev.get("event", "")
    ev_name: str = ev.get("name", "")
    ev_data: dict[str, Any] = ev.get("data", {})

    if ev_type == "on_chain_end" and ev_name == "planner_node":
        output = ev_data.get("output", {}) or {}
        return StreamEvent(type="plan", seq=seq, data={"node": "planner_node", "output": output})

    if ev_type == "on_chain_start" and ev_name == "tool_node":
        return StreamEvent(type="tool_start", seq=seq, data={"node": "tool_node"})

    if ev_type == "on_chain_end" and ev_name == "tool_node":
        output = ev_data.get("output", {}) or {}
        return StreamEvent(type="tool_end", seq=seq, data={"node": "tool_node", "output": output})

    if ev_type == "on_chain_end" and ev_name == "LangGraph":
        output = ev_data.get("output", {}) or {}
        return StreamEvent(
            type="done",
            seq=seq,
            data={
                "output": output,
            },
        )

    if ev_type == "on_chat_model_stream":
        chunk = ev_data.get("chunk", {})
        text = ""
        if hasattr(chunk, "content"):
            text = str(chunk.content)
        elif isinstance(chunk, dict):
            text = str(chunk.get("content", ""))
        return StreamEvent(type="token", seq=seq, data={"text": text})

    # Skip: on_chain_start/LangGraph, on_chain_stream/*, _route_after_planner, etc.
    return None


# ---------------------------------------------------------------------------
# SSE streaming generator
# ---------------------------------------------------------------------------


_persona_populated_sessions: set[str] = set()
"""C.5 Plan 3 session-start dedupe — best-effort per-process cache.

避免每 turn 重跑 4 次 PG query. 生产可换成 PG 标记 / Redis ttl, 当前 portfolio
范围只防 in-process 重跑就够用.
"""


async def _stream_chat(
    req: ChatRequest,
    user: _AnonUser,
    graph: CompiledStateGraph[Any, Any, Any, Any],
    extractor: EscalationExtractor | None,
    record_repo: EscalationRecordRepo | None,
) -> AsyncIterator[str]:
    """Async generator: drive astream_events and yield SSE-framed JSON strings.

    Each emitted SSE frame includes:
    - ``event: <type>`` line  (SSE named-event, enables browser EventSource filtering)
    - ``id: <seq>`` line      (last_event_id for reconnect per spec § 4.6 / G1)
    - ``data: <JSON>``        (StreamEvent payload without the `type` field)

    Plan 3 escalation: after the main LangGraph stream finishes, if
    ``final_state.escalate_offered`` is True, two additional events are emitted:
    1. ``escalate_request``    — signals the intent to escalate, includes reason.
    2. ``escalate_packet_draft`` — EscalationPacket draft + persisted record id.

    If ``extractor`` or ``record_repo`` are None (e.g. not yet wired in app_main),
    escalation events are skipped and a warning is logged.

    C.5 Plan 3: session-start hook — 第一个 turn 跑 populate_persona_on_session_start
    填 working_blocks(persona). 失败仅 log 不阻塞 chat.
    """
    # C.5 Plan 3: persona auto-injection (best-effort, fail-safe)
    session_key = f"{user.id}:{req.session_id}"
    if session_key not in _persona_populated_sessions:
        _persona_populated_sessions.add(session_key)
        try:
            from app.memory.persona_populator import populate_persona_on_session_start

            pg_factory = _build_async_pg_session_factory_or_none()
            if pg_factory is not None:
                user_uuid = user.id if isinstance(user.id, UUID) else UUID(str(user.id))
                populate_persona_on_session_start(pg_factory, user_id=user_uuid)
        except Exception as exc:  # noqa: BLE001
            logger.warning("populate_persona_on_session_start failed: %s", exc)

    request_id = f"req-{uuid4().hex[:12]}"
    initial = GraphState(
        user_id=user.id,
        session_id=req.session_id,
        user_message=req.message,
        enable_web_search=req.enable_web_search,
        enable_kb_search=req.enable_kb_search,
        request_id=request_id,
        trace_request_id=request_id,  # v0.9 observability; same as request_id at entry
    )
    config: RunnableConfig = {"configurable": {"thread_id": f"{user.id}:{req.session_id}"}}

    seq = 0

    def next_seq() -> int:
        nonlocal seq
        seq += 1
        return seq

    final_state: dict[str, Any] | None = None

    try:
        async for ev in graph.astream_events(initial.model_dump(), config=config, version="v2"):
            # Capture top-level graph final state for post-stream escalation check
            if ev.get("event") == "on_chain_end" and ev.get("name") == "LangGraph":
                final_state = (ev.get("data") or {}).get("output") or {}

            sse = _adapt_event(ev, next_seq())
            if sse is not None:
                yield (
                    f"event: {sse.type}\n"
                    f"id: {sse.seq}\n"
                    f"data: {sse.model_dump_json(exclude={'type'})}\n\n"
                )
    except Exception as exc:
        error_event = StreamEvent(
            type="error",
            seq=next_seq(),
            data={"message": str(exc), "traceback": traceback.format_exc()},
        )
        yield (
            f"event: {error_event.type}\n"
            f"id: {error_event.seq}\n"
            f"data: {error_event.model_dump_json(exclude={'type'})}\n\n"
        )
        return  # don't attempt escalation after a graph-level error

    # ------------------------------------------------------------------
    # Plan 3 E2: emit escalate events when planner offered escalation
    # ------------------------------------------------------------------
    if not (final_state and final_state.get("escalate_offered")):
        return

    if extractor is None or record_repo is None:
        logger.warning(
            "escalate_offered=True but EscalationExtractor/EscalationRecordRepo not wired; "
            "skipping escalation events (configure deps in app_main lifespan, Task 11)"
        )
        return

    # Extract escalate_reason from the plan stored in final_state
    raw_plan = final_state.get("plan")
    if isinstance(raw_plan, dict):
        reason: str = raw_plan.get("escalate_reason") or ""
    elif raw_plan is not None:
        reason = getattr(raw_plan, "escalate_reason", None) or ""
    else:
        reason = ""

    # 1. Emit escalate_request
    evt_req = StreamEvent(
        type="escalate_request",
        seq=next_seq(),
        data={"session_id": req.session_id, "reason": reason},
    )
    yield (
        f"event: {evt_req.type}\n"
        f"id: {evt_req.seq}\n"
        f"data: {evt_req.model_dump_json(exclude={'type'})}\n\n"
    )

    # 2. Build history_dicts for extractor
    raw_history = final_state.get("history") or []
    history_dicts: list[dict[str, Any]] = []
    for h in raw_history:
        if isinstance(h, dict):
            history_dicts.append({"role": h.get("role", ""), "content": h.get("content", "")})
        else:
            history_dicts.append(
                {"role": getattr(h, "role", ""), "content": getattr(h, "content", "")}
            )

    # 3. Build cached_tool_results list from tool_result_cache in final_state
    raw_cache = final_state.get("tool_result_cache") or {}
    cached_tool_results: list[dict[str, Any]] = []
    for cache_id, entry in raw_cache.items() if isinstance(raw_cache, dict) else []:
        if isinstance(entry, dict):
            cached_tool_results.append(
                {
                    "tool_name": entry.get("tool_name", ""),
                    "tool_args": {},
                    "result_summary": entry.get("result_summary", ""),
                    "cache_id": cache_id,
                }
            )
        else:
            cached_tool_results.append(
                {
                    "tool_name": getattr(entry, "tool_name", ""),
                    "tool_args": {},
                    "result_summary": getattr(entry, "result_summary", ""),
                    "cache_id": cache_id,
                }
            )

    # 4. Run extraction + persist draft, then emit escalate_packet_draft
    try:
        packet = await extractor.run(
            chat_session_id=req.session_id,
            chat_turn_count=len(history_dicts),
            chat_history_summary=final_state.get("history_summary"),
            history=history_dicts,
            cached_tool_results=cached_tool_results,
        )
        rec = await record_repo.create_draft(
            session_id=req.session_id,
            packet_draft=packet.model_dump(mode="json"),
        )
        evt_draft = StreamEvent(
            type="escalate_packet_draft",
            seq=next_seq(),
            data={
                "draft_record_id": str(rec.id),
                "packet": packet.model_dump(mode="json"),
            },
        )
        yield (
            f"event: {evt_draft.type}\n"
            f"id: {evt_draft.seq}\n"
            f"data: {evt_draft.model_dump_json(exclude={'type'})}\n\n"
        )
    except Exception as exc:
        logger.exception("escalation extraction/persist failed: %s", exc)
        err_evt = StreamEvent(
            type="error",
            seq=next_seq(),
            data={"error_msg": f"escalation extraction failed: {exc}"},
        )
        yield (
            f"event: {err_evt.type}\n"
            f"id: {err_evt.seq}\n"
            f"data: {err_evt.model_dump_json(exclude={'type'})}\n\n"
        )


# ---------------------------------------------------------------------------
# Route handler
# ---------------------------------------------------------------------------


@router.post("/api/v0/chat")
async def chat(
    req: ChatRequest,
    user: _AnonUser = Depends(get_current_user),
    chat_agent_graph: CompiledStateGraph[Any, Any, Any, Any] = Depends(get_chat_graph),
    extractor: EscalationExtractor = Depends(get_escalation_extractor),
    record_repo: EscalationRecordRepo = Depends(get_escalation_record_repo),
) -> StreamingResponse:
    """POST /api/v0/chat — stream a chat response as SSE.

    Request body: ChatRequest (session_id, message, optional flags).
    Response: text/event-stream per spec § 4.6.

    Each SSE frame has the form::

        event: <type>
        id: <seq>
        data: {"seq": <n>, "data": {...}}

    Full event type set defined in StreamEvent.type (see spec § 4.6).
    The ``done`` event signals the end of the stream.

    Plan 3 escalation: if the planner emits escalate_offered=True, two
    additional events follow the ``done`` event:
    ``escalate_request`` then ``escalate_packet_draft``.
    These require EscalationExtractor + EscalationRecordRepo to be wired
    via dependency_overrides (tests) or app_main lifespan (production).
    """
    return StreamingResponse(
        _stream_chat(req, user, chat_agent_graph, extractor, record_repo),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
