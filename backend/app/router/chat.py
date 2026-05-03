"""HTTP POST /api/v0/chat — SSE streaming chat endpoint.

Wires together:
- ChatRequest / StreamEvent Pydantic models (per spec § 5)
- get_chat_graph() DI: lazy singleton CompiledStateGraph
- get_current_user() DI: v0 stub (anonymous) — real auth preserved in auth_router
- _stream_chat(): async generator over LangGraph astream_events → SSE frames
- _adapt_event(): maps LangGraph event types to the 6 v0 StreamEvent types

Event mapping (from Spike 2 probe; confirmed against real astream_events output):
  on_chain_end / planner_node     → plan
  on_chain_start / tool_node      → tool_start
  on_chain_end / tool_node        → tool_end
  on_chain_end / LangGraph        → done  (top-level graph end)
  on_chat_model_stream             → token (v0 Responder uses sync chat; may not appear)
  all other events                → None (skipped)
  any unhandled exception          → error (best-effort, stream continues)
"""

from __future__ import annotations

import traceback
from collections.abc import AsyncIterator
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends
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
    type: Literal["plan", "tool_start", "tool_end", "token", "done", "error"]
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


def _build_graph_singleton() -> CompiledStateGraph[Any, Any, Any, Any]:
    """Build the CompiledStateGraph once and cache it as a module-level singleton.

    Build sequence:
    1. build_llm_service_from_env()  — real LLMService (LLM_MODE drives
       which client is used at env-var dispatch time, not here).
    2. build_tushare_service()        — mock or real per TUSHARE_MODE env var
    3. MockBochaService()            — reads LLMConfig internally
    4. Register StockQuoteTool / GetFinancialsTool / GetNewsTool
    5. ChatPlanner + Responder
    6. build_chat_graph with SQLite checkpointer for session isolation

    Thread safety: FastAPI runs in a single async event loop for the
    startup sequence; the singleton is set before requests arrive.
    For multi-worker deployments the per-worker singleton is acceptable
    since LangGraph state isolation is provided by thread_id, not process.
    """
    from pathlib import Path

    from app.agents.chat_planner import ChatPlanner
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

    db_path = Path("backend/data/chat.sqlite")
    return build_chat_graph(
        planner=planner, responder=responder, registry=registry, db_path=db_path
    )


def get_chat_graph() -> CompiledStateGraph[Any, Any, Any, Any]:
    """FastAPI dependency: return the module-level singleton graph."""
    global _graph_singleton
    if _graph_singleton is None:
        _graph_singleton = _build_graph_singleton()
    return _graph_singleton


# ---------------------------------------------------------------------------
# SSE event adapter
# ---------------------------------------------------------------------------

_VALID_TYPES = {"plan", "tool_start", "tool_end", "token", "done", "error"}


def _adapt_event(ev: dict[str, Any]) -> StreamEvent | None:
    """Translate a LangGraph astream_events dict into a v0 StreamEvent or None.

    Mapping (confirmed by Spike 2 local probe):
      on_chain_end   + planner_node  → plan       (plan decided)
      on_chain_start + tool_node     → tool_start
      on_chain_end   + tool_node     → tool_end
      on_chain_end   + LangGraph     → done       (top-level graph finished)
      on_chat_model_stream           → token      (streaming token; v0 may not emit)
      all others                     → None (skip)
    """
    ev_type: str = ev.get("event", "")
    ev_name: str = ev.get("name", "")
    ev_data: dict[str, Any] = ev.get("data", {})

    if ev_type == "on_chain_end" and ev_name == "planner_node":
        output = ev_data.get("output", {}) or {}
        return StreamEvent(type="plan", data={"node": "planner_node", "output": output})

    if ev_type == "on_chain_start" and ev_name == "tool_node":
        return StreamEvent(type="tool_start", data={"node": "tool_node"})

    if ev_type == "on_chain_end" and ev_name == "tool_node":
        output = ev_data.get("output", {}) or {}
        return StreamEvent(type="tool_end", data={"node": "tool_node", "output": output})

    if ev_type == "on_chain_end" and ev_name == "LangGraph":
        output = ev_data.get("output", {}) or {}
        return StreamEvent(
            type="done",
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
        return StreamEvent(type="token", data={"text": text})

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
    """Async generator: drive astream_events and yield SSE-framed JSON strings."""
    request_id = f"req-{uuid4().hex[:12]}"
    initial = GraphState(
        user_id=user.id,
        session_id=req.session_id,
        user_message=req.message,
        enable_web_search=req.enable_web_search,
        enable_kb_search=req.enable_kb_search,
        request_id=request_id,
    )
    config: RunnableConfig = {"configurable": {"thread_id": f"{user.id}:{req.session_id}"}}

    try:
        async for ev in graph.astream_events(initial.model_dump(), config=config, version="v2"):
            sse = _adapt_event(ev)
            if sse is not None:
                yield f"data: {sse.model_dump_json()}\n\n"
    except Exception as exc:
        error_event = StreamEvent(
            type="error",
            data={"message": str(exc), "traceback": traceback.format_exc()},
        )
        yield f"data: {error_event.model_dump_json()}\n\n"


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
    Response: text/event-stream where each line is ``data: <StreamEvent JSON>``.

    StreamEvent types: plan | tool_start | tool_end | token | done | error.
    The done event signals the end of the stream.
    """
    return StreamingResponse(
        _stream_chat(req, user, chat_agent_graph),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
