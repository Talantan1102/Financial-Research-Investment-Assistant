"""POST /api/v0.5/research SSE streaming endpoint."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agents.schemas import (
    ResearchRequest,
    ResearchState,
)
from app.router.chat import _AnonUser, get_current_user  # reuse v0 stub auth

router = APIRouter(tags=["research-v0.5"])


class ResearchStreamEvent(BaseModel):
    type: Literal[
        "plan",
        "data_progress",
        "insight",
        "report_chunk",
        "critic_score",
        "done",
        "error",
    ]
    data: dict[str, Any] = Field(default_factory=dict)


def _adapt_event(ev: dict[str, Any]) -> ResearchStreamEvent | None:
    """LangGraph event → ResearchStreamEvent (or None to skip).

    Event mapping:
      on_chain_end / research_planner_node → plan
      on_chain_end / data_collector_node   → data_progress
      on_chain_end / analyst_node          → insight
      on_chain_end / writer_node           → report_chunk
      on_chain_end / scorer_*              → critic_score
      on_chain_end / LangGraph (root only) → done
        (root = parent_ids is empty; critic subgraph also emits LangGraph
         but with non-empty parent_ids — those are skipped)
      all others                           → None (skipped)
    """
    et = ev.get("event")
    name = ev.get("name", "")

    if et == "on_chain_end":
        if name == "research_planner_node":
            return ResearchStreamEvent(type="plan", data={"name": name})
        if name == "data_collector_node":
            return ResearchStreamEvent(type="data_progress", data={"name": name})
        if name == "analyst_node":
            return ResearchStreamEvent(type="insight", data={"name": name})
        if name == "writer_node":
            return ResearchStreamEvent(type="report_chunk", data={"name": name})
        if name.startswith("scorer_"):
            return ResearchStreamEvent(type="critic_score", data={"scorer": name})
        if name == "LangGraph":
            # Only emit done for the outermost graph completion.
            # The critic subgraph also emits name="LangGraph" but with
            # non-empty parent_ids — those must be skipped to avoid
            # duplicate done events.
            parent_ids: list[str] = ev.get("parent_ids") or []
            if not parent_ids:
                return ResearchStreamEvent(type="done", data={})
    return None


_RESEARCH_GRAPH_SINGLETON: Any = None


def get_research_graph() -> Any:
    """DI factory: build the research graph singleton at first request (lazy init)."""
    global _RESEARCH_GRAPH_SINGLETON
    if _RESEARCH_GRAPH_SINGLETON is not None:
        return _RESEARCH_GRAPH_SINGLETON

    from app.agents.analyst import Analyst
    from app.agents.critic import Critic
    from app.agents.critic_subagents.conciseness import ConcisenessScorer
    from app.agents.critic_subagents.coverage import CoverageScorer
    from app.agents.critic_subagents.factuality import FactualityScorer
    from app.agents.critic_subagents.insight import InsightScorer
    from app.agents.critic_subagents.structure import StructureScorer
    from app.agents.data_collector import DataCollector
    from app.agents.research_planner import ResearchPlanner
    from app.agents.writer import Writer
    from app.orchestration.research_graph import build_research_graph
    from app.services.bocha_factory import build_bocha_service_from_env
    from app.services.kb_factory import build_kb_search_service_from_env
    from app.services.openai_client import build_llm_service_from_env
    from app.services.tushare_factory import build_tushare_service
    from app.tools.get_financials import GetFinancialsTool
    from app.tools.get_news import GetNewsTool
    from app.tools.get_stock_quote import StockQuoteTool
    from app.tools.kb_search import KbSearchTool
    from app.tools.registry import ToolRegistry
    from app.tools.web_search import WebSearchTool

    llm = build_llm_service_from_env()
    tushare = build_tushare_service()

    registry = ToolRegistry()
    registry.register(StockQuoteTool(tushare=tushare))
    registry.register(GetFinancialsTool(tushare=tushare))
    registry.register(GetNewsTool(bocha=build_bocha_service_from_env()))
    registry.register(WebSearchTool(bocha=build_bocha_service_from_env()))
    kb_service = build_kb_search_service_from_env()
    registry.register(KbSearchTool(kb_service=kb_service))

    planner = ResearchPlanner(llm=llm)
    collector = DataCollector(llm=llm, registry=registry)
    analyst = Analyst(llm=llm)
    writer = Writer(llm=llm)
    scorers = [
        FactualityScorer(llm=llm),
        CoverageScorer(llm=llm),
        InsightScorer(llm=llm),
        StructureScorer(llm=llm),
        ConcisenessScorer(llm=llm),
    ]
    critic = Critic(llm=llm, scorers=scorers)

    _RESEARCH_GRAPH_SINGLETON = build_research_graph(
        planner=planner,
        collector=collector,
        analyst=analyst,
        writer=writer,
        critic=critic,
        db_path=Path("backend/data/research.sqlite"),
    )
    return _RESEARCH_GRAPH_SINGLETON


@router.post("/api/v0.5/research")
async def research(
    req: ResearchRequest,
    user: _AnonUser = Depends(get_current_user),
    graph: Any = Depends(get_research_graph),
) -> StreamingResponse:
    """POST /api/v0.5/research — stream a research report as SSE.

    Request body: ResearchRequest (user_message, optional target_entity + research_style).
    Response: text/event-stream where each line is ``data: <ResearchStreamEvent JSON>``.

    ResearchStreamEvent types:
      plan | data_progress | insight | report_chunk | critic_score | done | error.
    The done event signals the end of the stream.
    """
    return StreamingResponse(
        _stream_research(req, user, graph),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _stream_research(req: ResearchRequest, user: _AnonUser, graph: Any) -> AsyncIterator[str]:
    """Async generator: drive astream_events and yield SSE-framed JSON strings."""
    request_id = f"research-{uuid4().hex[:12]}"
    initial = ResearchState(
        user_id=user.id,
        session_id=request_id,
        user_message=req.user_message or f"请对 {req.target_ts_code} 进行投资标的尽调。",
        request_id=request_id,
        target_ts_code=req.target_ts_code,
        client_total_aum=req.client_total_aum,
        client_existing_position=req.client_existing_position,
        investment_objective=req.investment_objective,
        investment_horizon=req.investment_horizon,
        risk_tolerance=req.risk_tolerance,
    )
    config = {"configurable": {"thread_id": f"research:{user.id}:{request_id}"}}

    try:
        async for ev in graph.astream_events(initial.model_dump(), config=config, version="v2"):
            adapted = _adapt_event(ev)
            if adapted is not None:
                yield f"data: {adapted.model_dump_json()}\n\n"
    except Exception as e:
        err = ResearchStreamEvent(type="error", data={"message": str(e)})
        yield f"data: {err.model_dump_json()}\n\n"
