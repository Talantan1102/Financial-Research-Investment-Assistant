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

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel

from app.agents.escalation_extractor import EscalationExtractor
from app.agents.schemas import GraphState
from app.router.chat_finalize import finalize_task_persistence
from app.services.chat_session_repo import ChatSessionRepo
from app.services.chat_task_repo import ChatTaskRepo
from app.services.escalation_record_repo import EscalationRecordRepo

if TYPE_CHECKING:
    from redis.asyncio import Redis as AsyncRedis

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


def get_async_session_factory(request: Request) -> Any | None:
    """Return the async PG session factory wired by app_main lifespan, or None.

    Plan 1 Task 5: POST /api/v0/chat reads this dependency to decide whether to
    persist chat messages + task rows. If the factory is None (test path / dev
    without PG), the handler degrades gracefully to legacy streaming-only
    behavior so existing SSE tests keep passing.

    Sourced from ``app.state.async_session_factory`` (set in app_main.lifespan).
    Overridden in tests via ``dependency_overrides[get_async_session_factory]``
    to inject an in-memory sqlite ``async_sessionmaker``.
    """
    return getattr(request.app.state, "async_session_factory", None)


def get_redis_async(request: Request) -> AsyncRedis | None:
    """Plan 2: Redis async client wired by app_main lifespan to app.state.redis_async.

    Returns None if Redis is not configured — endpoints that need it 503 gracefully.
    Overridden in tests via ``dependency_overrides[get_redis_async]`` to inject
    a fakeredis instance.
    """
    return getattr(request.app.state, "redis_async", None)


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
# Stub User — v0 anonymous auth. C44: single source in auth_helpers (chat.py
# previously kept a byte-for-byte duplicate); re-export so the Depends usages
# below resolve to the shared definitions and future auth changes propagate.
# ---------------------------------------------------------------------------
from app.router.auth_helpers import _AnonUser, get_current_user  # noqa: E402

# ---------------------------------------------------------------------------
# Graph singleton — built once at lifespan startup, stored on app.state.chat_graph
# ---------------------------------------------------------------------------


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


async def _build_graph_singleton(
    *,
    mcp_client: Any,
    checkpointer: Any | None = None,
) -> CompiledStateGraph[Any, Any, Any, Any]:
    """Build the CompiledStateGraph once and cache it as a module-level singleton.

    All tools are sourced from the MCP server subprocess via `mcp_client`. This
    is the single tool-interface boundary for chat mode — there is no in-process
    Tool registration. The MCP server exposes 8 chat-profile tools:
        get_stock_quote / get_financial_statements / get_market_indicators /
        get_corporate_actions / get_news / web_search / kb_search /
        compare_stocks
    (Reference: app/mcp_server/server.py:_CHAT_TOOL_MODULES)

    Build sequence:
      1. build_llm_service_from_env()  — real LLMService
      2. ToolRegistry().register_mcp_client_async(mcp_client) — populate from MCP
      3. HierarchicalMemory (with PG) or InSessionMemory (no PG) fallback
      4. ChatPlanner (passed memory + tool whitelist from MCP) + Responder
      5. build_chat_graph (PG checkpointer optional)

    Args:
        mcp_client: MCPClient connected to the chat_tools-profile subprocess.
            Required — chat graph has no in-process tool fallback.
        checkpointer: PG checkpointer for LangGraph state persistence (optional).

    Raises:
        ValueError: if mcp_client is None.
    """
    from app.agents.chat_planner import ChatPlanner
    from app.agents.in_session_memory import InSessionMemory
    from app.agents.responder import Responder
    from app.memory.hierarchical import HierarchicalMemory
    from app.orchestration.chat_graph import build_chat_graph
    from app.services.openai_client import build_llm_service_from_env
    from app.tools.registry import ToolRegistry

    if mcp_client is None:
        raise ValueError(
            "_build_graph_singleton requires a live mcp_client; chat graph "
            "has no in-process tool fallback after the MCP-only refactor."
        )

    llm = build_llm_service_from_env()

    registry = ToolRegistry()
    await registry.register_mcp_client_async(mcp_client)

    # C.5 Plan 1B: HierarchicalMemory 是主 Memory Protocol 实现; InSessionMemory
    # 仅作 PG 不可用时的 fallback (保 Q4 E in-session dedup behavior)。
    pg_factory = _build_async_pg_session_factory_or_none()
    memory: Any
    if pg_factory is None:
        memory = InSessionMemory(llm=llm)
    else:
        memory = HierarchicalMemory(
            pg_session_factory=pg_factory,
            age_executor=None,
            milvus_client=None,
            embed_service=None,
            llm_extractor=None,
            llm_judge=None,
        )

    planner = ChatPlanner(
        llm=llm,
        registry=registry,
        available_tools=[t["function"]["name"] for t in registry.list_for_llm()],
        memory=memory,
    )
    responder = Responder(llm=llm)

    # ToolResultCache placeholder — async_engine 入站尚未 wire; 用 no-op stub。
    class _NoOpCache:
        """Stub ToolResultCache that always misses."""

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
    """FastAPI dependency: return the lifespan-built chat graph from app.state.

    Lifespan (app_main.py) builds the graph after MCPClient subprocess is up
    and stores it on app.state.chat_graph. Test code that wants to bypass
    lifespan can set app.dependency_overrides[get_chat_graph] = lambda: <stub>.
    """
    graph: CompiledStateGraph[Any, Any, Any, Any] | None = getattr(
        request.app.state, "chat_graph", None
    )
    if graph is None:
        raise RuntimeError(
            "chat_graph not initialized on app.state — lifespan must run "
            "_build_graph_singleton before any /chat request. If this fires "
            "in tests, use dependency_overrides[get_chat_graph] instead."
        )
    return graph


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


def _coerce_user_uuid(user_id: Any) -> UUID | None:
    """Resolve a possibly-anonymous user_id into a real UUID or None.

    Production users have UUID; the v0 stub uses ``"anonymous"`` and test code
    uses ``"test-user"``. Non-UUID strings (anonymous / test stub) → None so
    that ChatTask.user_id stays NULL pre-auth — matches ChatSession.user_id's
    nullable behavior. Production PG FK (``users.id``) would otherwise reject
    a synthetic uuid5 that has no matching row in ``users``.

    C.6 接 JWT 后,user.id 永远是真 UUID,本函数走直通分支。
    """
    if isinstance(user_id, UUID):
        return user_id
    s = str(user_id)
    try:
        return UUID(s)
    except (ValueError, AttributeError):
        return None  # anonymous / test stub → NULL in DB


async def _stream_chat(
    req: ChatRequest,
    user: _AnonUser,
    graph: CompiledStateGraph[Any, Any, Any, Any],
    extractor: EscalationExtractor | None,
    record_repo: EscalationRecordRepo | None,
    *,
    task_id: UUID | None = None,
    pg_factory: Any | None = None,
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
    # C.5 Plan 3: persona auto-injection (best-effort, fail-safe).
    # NOTE: use a distinct local name (``persona_pg_factory``) so we do not
    # shadow the ``pg_factory`` kwarg used by Plan 1 finalize_task_persistence.
    session_key = f"{user.id}:{req.session_id}"
    if session_key not in _persona_populated_sessions:
        _persona_populated_sessions.add(session_key)
        try:
            from app.memory.persona_populator import populate_persona_on_session_start

            persona_pg_factory = _build_async_pg_session_factory_or_none()
            if persona_pg_factory is not None:
                user_uuid = user.id if isinstance(user.id, UUID) else UUID(str(user.id))
                # C14: populate_persona_on_session_start runs ~6 blocking PG queries +
                # commit; offload off the event loop so it doesn't stall concurrent SSE.
                await asyncio.to_thread(
                    populate_persona_on_session_start, persona_pg_factory, user_id=user_uuid
                )
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
    # Plan 1 Task 5: accumulate token text for assistant message persistence.
    acc_assistant: list[str] = []
    graph_error: Exception | None = None

    try:
        try:
            async for ev in graph.astream_events(initial.model_dump(), config=config, version="v2"):
                # Capture top-level graph final state for post-stream escalation check
                if ev.get("event") == "on_chain_end" and ev.get("name") == "LangGraph":
                    final_state = (ev.get("data") or {}).get("output") or {}

                sse = _adapt_event(ev, next_seq())
                if sse is not None:
                    # Plan 1: accumulate token-event text for finally-block persistence
                    if sse.type == "token" and isinstance(sse.data, dict):
                        acc_assistant.append(str(sse.data.get("text", "")))
                    yield (
                        f"event: {sse.type}\n"
                        f"id: {sse.seq}\n"
                        f"data: {sse.model_dump_json(exclude={'type'})}\n\n"
                    )
        except Exception as exc:
            graph_error = exc
            # C30: log full context server-side (was Rule-5 invisible); NEVER leak
            # the traceback / internal paths to the SSE client.
            logger.exception(
                "Graph error in _stream_chat request_id=%s session_id=%s: %s",
                request_id,
                req.session_id,
                exc,
            )
            error_event = StreamEvent(
                type="error",
                seq=next_seq(),
                data={"message": "Internal error; please retry", "request_id": request_id},
            )
            yield (
                f"event: {error_event.type}\n"
                f"id: {error_event.seq}\n"
                f"data: {error_event.model_dump_json(exclude={'type'})}\n\n"
            )
            # fall through to finally; skip escalation post-processing below
    finally:
        # Plan 1 Task 5: persist assistant message + mark chat_task status.
        # Best-effort — failures here MUST NOT crash the SSE stream.
        if pg_factory is not None and task_id is not None:
            try:
                await finalize_task_persistence(
                    pg_factory=pg_factory,
                    task_id=task_id,
                    session_id=req.session_id,
                    graph=graph,
                    config=config,
                    final_state=final_state,
                    accumulated_token_text="".join(acc_assistant),
                    graph_error=graph_error,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("Plan 1 finalize_task_persistence failed: %s", exc)

    if graph_error is not None:
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
            request_id=request_id,  # C26: span linkage to the originating request
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


@router.post("/api/v0/chat", response_model=None)
async def chat(
    req: ChatRequest,
    user: _AnonUser = Depends(get_current_user),
    chat_agent_graph: CompiledStateGraph[Any, Any, Any, Any] = Depends(get_chat_graph),
    extractor: EscalationExtractor = Depends(get_escalation_extractor),
    record_repo: EscalationRecordRepo = Depends(get_escalation_record_repo),
    pg_factory: Any | None = Depends(get_async_session_factory),
    redis: AsyncRedis | None = Depends(get_redis_async),
) -> StreamingResponse | dict[str, str]:
    """POST /api/v0/chat — chat entry endpoint(双 path,graceful degrade)。

    Plan 1 inline path(legacy):pg_factory wired but redis None →
    inline SSE streaming via ``_stream_chat``,response is text/event-stream。

    Plan 2 enqueue path:pg_factory + redis 都 wired → 持久化 user message +
    create chat_task + enqueue Celery `run_chat_async`,返 JSON
    ``{task_id, session_id, stream_url}``,前端用 GET /chat/stream/{tid}
    订阅 Redis Streams replay。

    Graceful degrade:
    - pg_factory + redis 都 None / 任一 None  → Plan 1 inline path (preserve
      Plan 1 production behavior + 老 SSE regression test 不破坏)
    - Plan 2 Task 7 wire ``app.state.redis_async`` 后 production 自动切到 Plan 2

    Request body: ChatRequest (session_id, message, optional flags).
    Responses:
        - Plan 1: text/event-stream (SSE, see spec § 4.6)
        - Plan 2: application/json (``{task_id, session_id, stream_url}``)

    Plan 3 escalation 流(escalate_request / escalate_packet_draft)目前仍
    inline 在 Plan 1 path,Plan 2 path 由 Celery worker chunk-level forward
    (out-of-scope for Task 5)。
    """
    # ===== Plan 2 new path: Celery enqueue + return JSON =====
    if pg_factory is not None and redis is not None:
        from app.tasks.chat_runner import enqueue_run_chat

        session_repo = ChatSessionRepo(pg_factory)
        task_repo = ChatTaskRepo(pg_factory)

        user_msg = await session_repo.append_message(
            session_id=req.session_id,
            role="user",
            content=req.message,
        )
        task = await task_repo.create_queued(
            session_id=req.session_id,
            user_id=_coerce_user_uuid(user.id),
            langgraph_thread_id=f"{user.id}:{req.session_id}",
            initial_prompt_message_id=user_msg.id,
        )

        enqueue_run_chat(
            task_id=str(task.id),
            session_id=req.session_id,
            user_id=str(user.id),
            user_message=req.message,
        )

        # === Async session title (2026-05-17): user msg 入库即触发, 跟 chat agent 并行
        # 跑;LLM 只读 user_msg, 不必等 assistant 完成, 比 chat_finalize 触发提前 ~5-10s
        # → "新对话" 中间态尽量短(目标 <2s vs assistant 落库后再花 1-2s 出 title)。
        # task 内部检查 title_source != "pending" 幂等 skip, 重复触发安全。
        try:
            session = await session_repo.get_session(str(req.session_id))
            if session and session.title_source == "pending":
                from app.tasks.title_generation import generate_session_title

                generate_session_title.apply_async(args=[str(req.session_id)])
                logger.info("enqueued generate_session_title for session %s", req.session_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("title enqueue skipped: %s", exc)

        return {
            "task_id": str(task.id),
            "session_id": req.session_id,
            "stream_url": f"/api/v0/chat/stream/{task.id}",
        }

    # ===== Plan 1 legacy path: inline SSE streaming (UNCHANGED behavior) =====
    task_id: UUID | None = None

    if pg_factory is not None:
        try:
            session_repo = ChatSessionRepo(pg_factory)
            task_repo = ChatTaskRepo(pg_factory)
            user_msg = await session_repo.append_message(
                session_id=req.session_id,
                role="user",
                content=req.message,
            )
            task = await task_repo.create_queued(
                session_id=req.session_id,
                user_id=_coerce_user_uuid(user.id),
                langgraph_thread_id=f"{user.id}:{req.session_id}",
                initial_prompt_message_id=user_msg.id,
            )
            await task_repo.mark_running(task.id)
            task_id = task.id
        except Exception as exc:  # noqa: BLE001
            # Best-effort: if persistence fails at entry, log and fall through to
            # legacy non-persisted stream — don't 500 the user-visible request.
            logger.exception("Plan 1 entry persistence failed; degrading to legacy path: %s", exc)
            task_id = None

    return StreamingResponse(
        _stream_chat(
            req,
            user,
            chat_agent_graph,
            extractor,
            record_repo,
            task_id=task_id,
            pg_factory=pg_factory if task_id is not None else None,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Plan 2 Task 4: GET /api/v0/chat/stream/{task_id} — SSE replay endpoint
# ---------------------------------------------------------------------------


@router.get("/api/v0/chat/stream/{task_id}")
async def chat_stream(
    task_id: str,
    request: Request,
    last_event_id: str = "0",
    pg_factory: Any | None = Depends(get_async_session_factory),
    redis: AsyncRedis | None = Depends(get_redis_async),
) -> StreamingResponse:
    """SSE replay endpoint — XREAD from Redis Streams + forward as SSE frames.

    Plan 2 Task 4:前端打开 SSE 后,我们从 Redis Stream 拉 chunk-level event 转发。
    Spec § 6.2:entry id 直接透传作为 SSE ``id:`` field → 前端断流时回传
    ``last_event_id`` 续读;§ 5.5:客户端断开 → 停转发(不杀 Celery task)。

    Args:
        task_id: ChatTask UUID
        last_event_id: Redis Stream entry id ("0" = from start; ``<ms>-<seq>``
            from a previous reconnect)

    Returns:
        text/event-stream with frames ``event: <type>\\nid: <entry_id>\\ndata: <json>\\n\\n``.

    Status codes:
        - 200: streaming OK
        - 404: invalid uuid OR task not found
        - 503: PG / Redis not wired
    """
    try:
        task_uuid = uuid.UUID(task_id)
    except (ValueError, AttributeError) as exc:
        raise HTTPException(status_code=404, detail=f"invalid task_id: {task_id}") from exc

    if pg_factory is None or redis is None:
        raise HTTPException(
            status_code=503,
            detail="chat streaming not configured (PG or Redis unavailable)",
        )

    task_repo = ChatTaskRepo(pg_factory)
    task = await task_repo.get_by_id(task_uuid)
    if task is None:
        raise HTTPException(status_code=404, detail=f"task {task_id} not found")

    session_id_uuid = task.session_id  # ChatTask.session_id is UUID

    async def _forward_sse() -> AsyncIterator[str]:
        # Inline import: ChatEventBus → redis.asyncio import; defer to runtime so
        # the chat router stays importable in dev environments without redis.
        from app.services.chat_event_bus import ChatEventBus

        bus = ChatEventBus(redis=redis)  # type: ignore[arg-type]
        cur_id = last_event_id
        while True:
            # Spec § 5.5: client disconnect → stop forwarding, do NOT kill Celery task.
            if await request.is_disconnected():
                logger.debug(
                    "client disconnected from /chat/stream/%s; stopping forward",
                    task_id,
                )
                return
            entries = await bus.xread_blocking(
                session_id_uuid,
                task_uuid,
                last_id=cur_id,
                count=20,
                block_ms=10_000,  # 10s block then re-check disconnect
            )
            if not entries:
                continue
            for entry_id, payload in entries:
                cur_id = entry_id
                ev_type = payload.get("type", "unknown")
                data_str = json.dumps(payload, ensure_ascii=False)
                yield f"event: {ev_type}\nid: {entry_id}\ndata: {data_str}\n\n"
                # Terminal events: stop the forward loop.
                if ev_type in ("done", "error_done"):
                    return

    return StreamingResponse(
        _forward_sse(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Plan 3 Task 4: POST /api/v0/chat/cancel/{task_id} — publish cancel signal
# ---------------------------------------------------------------------------


@router.post("/api/v0/chat/cancel/{task_id}", status_code=202)
async def chat_cancel(
    task_id: str,
    pg_factory: Any | None = Depends(get_async_session_factory),
    redis: AsyncRedis | None = Depends(get_redis_async),
) -> dict[str, str]:
    """Publish cancel signal to ``chat:cancel:{tid}`` channel.

    Spec § 5.3 Scenario C:用户点停止 → 立即 return 202(异步生效);worker 内
    listener 收到 signal → raise GraphInterrupt → finalize 走 partial commit
    (Plan 3 Task 3 已实施)。

    Status codes:
        - 202: cancel signal published (worker reacts async)
        - 404: invalid task_id (not UUID) OR task not found in PG
        - 503: PG / Redis 未 wire
    """
    try:
        task_uuid = uuid.UUID(task_id)
    except (ValueError, AttributeError) as exc:
        raise HTTPException(status_code=404, detail=f"invalid task_id: {task_id}") from exc

    if pg_factory is None or redis is None:
        raise HTTPException(
            status_code=503,
            detail="chat cancel not available — PG or Redis unavailable",
        )

    task_repo = ChatTaskRepo(pg_factory)
    task = await task_repo.get_by_id(task_uuid)
    if task is None:
        raise HTTPException(status_code=404, detail=f"task {task_id} not found")

    # Inline import: ChatCancelBus → redis.asyncio import; defer to runtime to
    # keep chat router importable in dev environments without redis configured.
    from app.services.chat_cancel_bus import ChatCancelBus

    cancel_bus = ChatCancelBus(redis=redis)  # type: ignore[arg-type]
    receivers = await cancel_bus.publish_cancel(task_uuid)
    return {
        "task_id": task_id,
        "receivers": str(receivers),
        "status": "cancel_published",
    }


# ---------------------------------------------------------------------------
# Plan 3 Task 5: POST /api/v0/chat/retry/{task_id} — resume failed task
# ---------------------------------------------------------------------------


@router.post("/api/v0/chat/retry/{task_id}")
async def chat_retry(
    task_id: str,
    pg_factory: Any | None = Depends(get_async_session_factory),
    redis: AsyncRedis | None = Depends(get_redis_async),
) -> dict[str, str]:
    """Retry failed/cancelled/partial task from LangGraph checkpoint.

    Spec § 5.4 Scenario D + § 6.4 retry 链:
    - task.status 必须 ∈ {error, partial, cancelled}(done / running / queued 拒)
    - task.langgraph_checkpoint_id 必须非空,否则 422(从头重跑要重发 prompt)
    - 创建新 chat_tasks row,parent_task_id=旧 tid,initial_prompt_message_id 沿用
    - enqueue Celery 带 resume_checkpoint_id,worker LangGraph 续跑

    Status codes:
        - 200: new task enqueued; body = {task_id, parent_task_id, stream_url,
          resumed_from_checkpoint}
        - 404: invalid task_id (not UUID) OR task not found
        - 409: task status ∉ retryable set
        - 422: task has no langgraph_checkpoint_id (early failure before commit)
        - 503: PG / Redis unavailable
    """
    try:
        task_uuid = uuid.UUID(task_id)
    except (ValueError, AttributeError) as exc:
        raise HTTPException(status_code=404, detail=f"invalid task_id: {task_id}") from exc

    if pg_factory is None or redis is None:
        raise HTTPException(
            status_code=503,
            detail="chat retry not available — PG or Redis unavailable",
        )

    task_repo = ChatTaskRepo(pg_factory)
    old_task = await task_repo.get_by_id(task_uuid)
    if old_task is None:
        raise HTTPException(status_code=404, detail=f"task {task_id} not found")

    if old_task.status not in ("error", "partial", "cancelled"):
        raise HTTPException(
            status_code=409,
            detail=(
                f"cannot retry task in status={old_task.status}; "
                "only error/partial/cancelled retryable"
            ),
        )
    if not old_task.langgraph_checkpoint_id:
        raise HTTPException(
            status_code=422,
            detail=(
                "cannot resume: task has no langgraph_checkpoint_id "
                "(early failure before any checkpoint commit)"
            ),
        )

    # Create new task linked to old (parent_task_id chain; initial prompt msg sticky)
    new_task = await task_repo.create_queued(
        session_id=old_task.session_id,
        user_id=old_task.user_id,
        langgraph_thread_id=old_task.langgraph_thread_id,
        initial_prompt_message_id=old_task.initial_prompt_message_id,
        parent_task_id=old_task.id,
    )

    # Inline import: chat_runner pulls Celery + redis; defer to runtime so the
    # chat router stays importable in dev environments without Celery configured.
    from app.tasks.chat_runner import enqueue_run_chat

    enqueue_run_chat(
        task_id=str(new_task.id),
        session_id=str(old_task.session_id),
        user_id=str(old_task.user_id) if old_task.user_id else "anonymous",
        # resume 不需要新 user_message — graph 从 checkpoint state 续跑,
        # 原始 user prompt 已经在 checkpoint 的 messages 里了。
        user_message="",
        resume_checkpoint_id=old_task.langgraph_checkpoint_id,
        parent_task_id=str(old_task.id),
    )

    return {
        "task_id": str(new_task.id),
        "parent_task_id": str(old_task.id),
        "stream_url": f"/api/v0/chat/stream/{new_task.id}",
        "resumed_from_checkpoint": old_task.langgraph_checkpoint_id,
    }


@router.get("/api/v0/tools")
async def list_chat_tools(request: Request) -> dict[str, Any]:
    """List MCP chat-profile tools (name/description/inputSchema) for the slash menu.

    Source of truth = the live MCP client's list_tools() — the 8 chat tools wired
    to the chat agent. Returns 503 if the MCP subprocess isn't up.
    """
    mcp_client = getattr(request.app.state, "mcp_client", None)
    if mcp_client is None:
        raise HTTPException(
            status_code=503, detail="tools unavailable — mcp_client not initialized"
        )
    tools = await mcp_client.list_tools()
    return {
        "tools": [
            {
                "name": t["name"],
                "description": t.get("description", ""),
                "inputSchema": t.get("inputSchema", {}),
            }
            for t in tools
        ]
    }
