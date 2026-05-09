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

StreamEvent.seq is a monotonic per-stream counter starting at 1, used for
last_event_id-based SSE reconnect (spec § 4.6 / G1 industrial problem).
"""

from __future__ import annotations

import traceback
from collections.abc import AsyncIterator
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel

from app.agents.schemas import GraphState

router = APIRouter(tags=["chat-v0"])

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

    # Q4 E: in-session memory for tool dedup + token-guard summarize
    memory = InSessionMemory(llm=llm)

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


async def _stream_chat(
    req: ChatRequest,
    user: _AnonUser,
    graph: CompiledStateGraph[Any, Any, Any, Any],
) -> AsyncIterator[str]:
    """Async generator: drive astream_events and yield SSE-framed JSON strings.

    Each emitted SSE frame includes:
    - ``event: <type>`` line  (SSE named-event, enables browser EventSource filtering)
    - ``id: <seq>`` line      (last_event_id for reconnect per spec § 4.6 / G1)
    - ``data: <JSON>``        (StreamEvent payload without the `type` field)
    """
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

    try:
        async for ev in graph.astream_events(initial.model_dump(), config=config, version="v2"):
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


# ---------------------------------------------------------------------------
# Route handler
# ---------------------------------------------------------------------------


@router.post("/api/v0/chat")
async def chat(
    req: ChatRequest,
    user: _AnonUser = Depends(get_current_user),
    chat_agent_graph: CompiledStateGraph[Any, Any, Any, Any] = Depends(get_chat_graph),
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
    """
    return StreamingResponse(
        _stream_chat(req, user, chat_agent_graph),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
