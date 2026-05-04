"""POST /api/v0.5/research SSE streaming endpoint + run history REST endpoints."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agents.schemas import (
    ResearchRequest,
    ResearchState,
)
from app.router.chat import _AnonUser, get_current_user  # reuse v0 stub auth

logger = logging.getLogger(__name__)

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
    from app.agents.critic_subagents.input_context_scorer import (
        InputContextAppropriatenessScorer,
    )
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
        InputContextAppropriatenessScorer(llm=llm),  # 第 6 scorer (v0.8.4)
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


# ── Run history REST endpoints ─────────────────────────────────────────────────


class ResearchRunSummary(BaseModel):
    """Summary of a past research run, for the history list page."""

    id: str  # request_id
    target_name: str
    target_ts_code: str
    generated_at: str  # ISO datetime string
    tldr: str
    recommendation: str


_MOCK_RUNS: list[ResearchRunSummary] = [
    ResearchRunSummary(
        id="demo-run-001",
        target_name="贵州茅台",
        target_ts_code="600519.SH",
        generated_at="2026-05-04T10:23:00",
        tldr="茅台护城河深厚，估值处于历史中位，适合中长期配置",
        recommendation="recommend_overweight",
    ),
    ResearchRunSummary(
        id="demo-run-002",
        target_name="宁德时代",
        target_ts_code="300750.SZ",
        generated_at="2026-05-04T09:10:00",
        tldr="电池龙头，成长性强，短期估值偏高需关注竞争格局",
        recommendation="recommend_hold",
    ),
]


def _read_research_runs_from_sqlite(db_path: Path, limit: int = 50) -> list[ResearchRunSummary]:
    """Read recent research runs from SqliteSaver checkpoint DB.

    The SqliteSaver stores thread snapshots in the `checkpoints` table.
    We join to `checkpoint_blobs` to fish out the ResearchState blob and
    extract investment_report fields.  If the DB does not yet exist or the
    table schema is unexpected, we fall back to mock data.

    TODO(Task 7 dogfood): replace mock fallback with proper error once we have
    real runs stored post-dogfood.
    """
    import sqlite3

    try:
        if not db_path.exists():
            return []

        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        cursor = conn.cursor()

        # SqliteSaver v1 schema: table `checkpoints` with columns
        # (thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata)
        # and `checkpoint_blobs` with (thread_id, checkpoint_ns, channel, type, blob).
        # We look for the latest checkpoint per research thread_id and extract
        # the `investment_report` channel blob.
        cursor.execute(
            """
            SELECT c.thread_id, cb.blob
            FROM checkpoints c
            JOIN checkpoint_blobs cb ON cb.thread_id = c.thread_id
            WHERE c.thread_id LIKE 'research:%'
              AND cb.channel = 'investment_report'
              AND cb.type = 'json'
            ORDER BY c.checkpoint_id DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cursor.fetchall()
        conn.close()

        results: list[ResearchRunSummary] = []
        seen_thread_ids: set[str] = set()
        for thread_id, blob in rows:
            if thread_id in seen_thread_ids:
                continue
            seen_thread_ids.add(thread_id)
            try:
                report_data = json.loads(blob)
                request_id = report_data.get("request_id", thread_id)
                target_name = report_data.get("target_name", "")
                target_ts_code = report_data.get("target_ts_code", "")
                generated_at = str(report_data.get("generated_at", ""))
                # TL;DR: use investment_recommendation.narrative first 80 chars
                rec = report_data.get("investment_recommendation", {})
                recommendation = rec.get("recommendation", "")
                narrative = rec.get("narrative", "")
                tldr = narrative[:80] + ("…" if len(narrative) > 80 else "")
                results.append(
                    ResearchRunSummary(
                        id=request_id,
                        target_name=target_name,
                        target_ts_code=target_ts_code,
                        generated_at=generated_at,
                        tldr=tldr,
                        recommendation=recommendation,
                    )
                )
            except Exception:
                continue
        return results

    except Exception:
        logger.exception("Failed to read research runs from sqlite; returning empty list")
        return []


@router.get("/api/v0.5/research/runs")
async def list_research_runs(
    limit: int = Query(default=50, ge=1, le=200),
) -> list[ResearchRunSummary]:
    """GET /api/v0.5/research/runs — list recent research run summaries.

    Reads from the SqliteSaver checkpoint DB at backend/data/research.sqlite.
    Falls back to hardcoded mock data when no real runs exist yet.

    TODO(Task 7 dogfood): remove mock fallback once real runs are stored.
    """
    db_path = Path("backend/data/research.sqlite")
    real_runs = _read_research_runs_from_sqlite(db_path, limit=limit)
    if real_runs:
        return real_runs
    # Mock data so the frontend history page renders during development.
    return _MOCK_RUNS


@router.get("/api/v0.5/research/{run_id}")
async def get_research_report(run_id: str) -> Any:
    """GET /api/v0.5/research/{run_id} — fetch a full InvestmentDueDiligenceReport.

    Looks up the checkpoint thread matching the given run_id (request_id)
    and returns the serialised InvestmentDueDiligenceReport.

    TODO(Task 7 dogfood): implement proper lookup once real runs are stored.
    """
    db_path = Path("backend/data/research.sqlite")
    try:
        if db_path.exists():
            import sqlite3

            conn = sqlite3.connect(str(db_path), check_same_thread=False)
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT cb.blob
                FROM checkpoints c
                JOIN checkpoint_blobs cb ON cb.thread_id = c.thread_id
                WHERE cb.channel = 'investment_report'
                  AND cb.type = 'json'
                  AND (c.thread_id LIKE ? OR cb.blob LIKE ?)
                ORDER BY c.checkpoint_id DESC
                LIMIT 1
                """,
                (f"%{run_id}%", f'%"request_id": "{run_id}"%'),
            )
            row = cursor.fetchone()
            conn.close()
            if row:
                return json.loads(row[0])
    except Exception:
        logger.exception("Failed to fetch research report %s from sqlite", run_id)

    raise HTTPException(status_code=404, detail=f"Research run {run_id!r} not found")


# ── Tushare stock autocomplete ─────────────────────────────────────────────────


class TsCodeSuggestion(BaseModel):
    ts_code: str
    name: str


_STOCK_BASIC_CACHE: list[TsCodeSuggestion] | None = None


async def _get_stock_basic_cache() -> list[TsCodeSuggestion]:
    """Lazy-load and cache stock_basic list from Tushare (or mock).

    When TUSHARE_MODE=real, calls the Tushare API via TushareClient.call().
    Otherwise (mock mode) falls back to the hardcoded list below.
    The result is cached in-process for the lifetime of the server.
    """
    global _STOCK_BASIC_CACHE
    if _STOCK_BASIC_CACHE is not None:
        return _STOCK_BASIC_CACHE

    import os

    if os.environ.get("TUSHARE_MODE", "mock").lower() == "real":
        try:
            from app.services.tushare_client import TushareClient

            token = os.environ.get("TUSHARE_TOKEN", "")
            base_url = os.environ.get("TUSHARE_BASE_URL", "http://api.tushare.pro")
            client = TushareClient(token=token, base_url=base_url)
            df = await client.call("stock_basic", {}, fields="ts_code,name")
            if df is not None and not df.empty:
                _STOCK_BASIC_CACHE = [
                    TsCodeSuggestion(ts_code=row["ts_code"], name=row["name"])
                    for _, row in df.iterrows()
                ]
                return _STOCK_BASIC_CACHE
        except Exception:
            logger.warning("stock_basic fetch failed, using hardcoded fallback")

    # Hardcoded fallback: common A-share stocks for demo.
    _STOCK_BASIC_CACHE = [
        TsCodeSuggestion(ts_code="600519.SH", name="贵州茅台"),
        TsCodeSuggestion(ts_code="000858.SZ", name="五粮液"),
        TsCodeSuggestion(ts_code="300750.SZ", name="宁德时代"),
        TsCodeSuggestion(ts_code="601318.SH", name="中国平安"),
        TsCodeSuggestion(ts_code="600036.SH", name="招商银行"),
        TsCodeSuggestion(ts_code="000651.SZ", name="格力电器"),
        TsCodeSuggestion(ts_code="000333.SZ", name="美的集团"),
        TsCodeSuggestion(ts_code="600900.SH", name="长江电力"),
        TsCodeSuggestion(ts_code="601899.SH", name="紫金矿业"),
        TsCodeSuggestion(ts_code="600887.SH", name="伊利股份"),
        TsCodeSuggestion(ts_code="002594.SZ", name="比亚迪"),
        TsCodeSuggestion(ts_code="601888.SH", name="中国中免"),
        TsCodeSuggestion(ts_code="600309.SH", name="万华化学"),
        TsCodeSuggestion(ts_code="300059.SZ", name="东方财富"),
        TsCodeSuggestion(ts_code="600276.SH", name="恒瑞医药"),
    ]
    return _STOCK_BASIC_CACHE


@router.get("/api/v0.5/tushare/stock_basic_search")
async def stock_basic_search(
    prefix: str = Query(default="", description="搜索前缀（股票名称或代码）"),
    limit: int = Query(default=10, ge=1, le=50),
) -> list[TsCodeSuggestion]:
    """GET /api/v0.5/tushare/stock_basic_search?prefix=... — ts_code autocomplete.

    Searches by name prefix (Chinese characters) or ts_code prefix.
    Returns up to `limit` matches.
    """
    if not prefix:
        return []

    pool = await _get_stock_basic_cache()
    prefix_lower = prefix.lower()
    matches = [
        s
        for s in pool
        if s.name.startswith(prefix)
        or s.ts_code.lower().startswith(prefix_lower)
        or prefix in s.name
    ]
    return matches[:limit]
