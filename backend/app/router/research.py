"""POST /api/v0.5/research SSE streaming endpoint + run history REST endpoints."""

from __future__ import annotations

import asyncio
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
from app.router.auth_helpers import _AnonUser, get_current_user

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


_TOOL_DISPLAY_LABELS: dict[str, str] = {
    "get_stock_quote": "实时行情",
    "get_financials": "财务报表",
    "get_news": "行业新闻",
    "web_search": "网络搜索",
    "kb_search": "知识库文档",
}

_SCORER_DISPLAY_LABELS: dict[str, str] = {
    "scorer_factuality": "事实准确性",
    "scorer_coverage": "覆盖完整度",
    "scorer_insight": "分析深度",
    "scorer_structure": "报告结构",
    "scorer_conciseness": "表达简洁性",
    "scorer_input_context": "客户适配度",
}


def _adapt_event(ev: dict[str, Any]) -> ResearchStreamEvent | None:
    """LangGraph event → ResearchStreamEvent (or None to skip).

    Event mapping:
      on_chain_end / research_planner_node → plan       (+ subtasks metadata)
      on_chain_end / data_collector_node   → data_progress (+ tools metadata)
      on_chain_end / analyst_node          → insight    (+ findings metadata)
      on_chain_end / writer_node           → report_chunk
      on_chain_end / scorer_*              → critic_score (individual scorer done)
      on_chain_end / aggregate             → critic_score (final aggregate scores)
      on_chain_end / LangGraph (root only) → done
        (root = parent_ids is empty; critic subgraph also emits LangGraph
         but with non-empty parent_ids — those are skipped)
      all others                           → None (skipped)

    Metadata fields (for business-friendly research log UX):
      plan:          summary str (业务化), subtasks list[str] (descriptions, max 5)
      data_progress: summary str (业务化), tools list[str] (human labels)
      insight:       summary str (业务化), findings list[str] (key findings, max 5)
      report_chunk:  chunk str (markdown content)
      critic_score:  summary str, scores dict (dimension → score), overall float
    """
    et = ev.get("event")
    name = ev.get("name", "")

    if et == "on_chain_end":
        if name == "research_planner_node":
            output: dict[str, Any] = ev.get("data", {}).get("output") or ev.get("output") or {}
            # plan comes back as a ResearchPlan instance or a dict
            plan_val = output.get("plan") or {}
            if hasattr(plan_val, "subtasks"):
                subtasks_raw = plan_val.subtasks or []
            else:
                subtasks_raw = plan_val.get("subtasks") or []
            subtask_descs: list[str] = []
            for s in subtasks_raw[:5]:
                if hasattr(s, "description"):
                    desc = str(s.description)
                else:
                    desc = str(s.get("description", ""))
                subtask_descs.append(desc[:60])
            n = len(subtasks_raw)
            # Business-friendly summary (hide internal agent name)
            summary = f"已拆解为 {n} 个研究维度" if n > 0 else "正在拆解研究路径..."
            return ResearchStreamEvent(
                type="plan",
                data={
                    "summary": f"📋 {summary}",
                    "subtasks": subtask_descs,
                    # keep name for AgentStatusSidebar in tech panel
                    "name": name,
                },
            )

        if name == "data_collector_node":
            output = ev.get("data", {}).get("output") or ev.get("output") or {}
            # tool_results is a list of ToolResult instances or dicts
            results_raw = output.get("tool_results") or []
            tool_names_raw: list[str] = []
            for r in results_raw:
                if hasattr(r, "tool_name"):
                    tool_names_raw.append(str(r.tool_name))
                else:
                    tool_names_raw.append(str(r.get("tool_name", "")))
            # Deduplicate tools (same tool called multiple times for different subtasks)
            seen: set[str] = set()
            unique_tools: list[str] = []
            for t in tool_names_raw:
                if t not in seen:
                    seen.add(t)
                    unique_tools.append(t)
            # Map to human-readable labels
            tool_labels = [_TOOL_DISPLAY_LABELS.get(t, t) for t in unique_tools]
            n = len(results_raw)
            summary = f"✅ 已采集 {n} 项数据"
            return ResearchStreamEvent(
                type="data_progress",
                data={
                    "summary": summary,
                    "tools": tool_labels,
                    # keep raw names for downstream (AgentStatusSidebar)
                    "tool_names_raw": tool_names_raw,
                    "name": name,
                },
            )

        if name == "analyst_node":
            output = ev.get("data", {}).get("output") or ev.get("output") or {}
            # insights is a list of Insight instances or dicts
            insights_raw = output.get("insights") or []
            findings: list[str] = []
            for item in insights_raw[:5]:
                if hasattr(item, "finding"):
                    finding = str(item.finding)
                else:
                    finding = str(item.get("finding", ""))
                findings.append(finding[:80] + ("..." if len(finding) > 80 else ""))
            n = len(insights_raw)
            summary = f"💡 已识别 {n} 项关键洞察" if n > 0 else "💡 正在综合分析..."
            return ResearchStreamEvent(
                type="insight",
                data={
                    "summary": summary,
                    "findings": findings,
                    "name": name,
                },
            )

        if name == "writer_node":
            # Extract report_markdown from node output so the frontend can
            # render the full report incrementally in the progress overlay.
            output = ev.get("data", {}).get("output") or ev.get("output") or {}
            md: str = output.get("report_markdown") or ""
            # Count sections (H2 headers) in markdown as proxy for report size
            section_count = md.count("\n## ")
            if section_count == 0:
                section_count = md.count("## ")
            section_str = f" ({section_count} 节)" if section_count > 0 else ""
            return ResearchStreamEvent(
                type="report_chunk",
                data={
                    "summary": f"📝 报告撰写完成{section_str}",
                    "chunk": md,
                    "name": name,
                },
            )

        if name == "aggregate":
            # Critic subgraph aggregate node: emit final CriticReport scores.
            # output is {"critic_report": CriticReport | dict}
            output = ev.get("data", {}).get("output") or ev.get("output") or {}
            report_val = output.get("critic_report")
            scores: dict[str, float] = {}
            overall = 0.0
            if report_val is not None:
                if hasattr(report_val, "dimensions"):
                    # Pydantic CriticReport model
                    for dim in report_val.dimensions:
                        scores[str(dim.dimension)] = float(dim.score)
                    overall = float(report_val.overall_score)
                elif isinstance(report_val, dict):
                    for dim in report_val.get("dimensions", []):
                        if isinstance(dim, dict):
                            scores[str(dim.get("dimension", ""))] = float(dim.get("score", 0))
                        else:
                            scores[str(dim.dimension)] = float(dim.score)
                    overall = float(report_val.get("overall_score", 0))
            # Build human-readable summary with key scores
            if scores:
                score_parts = []
                for dim_key, label in [
                    ("factuality", "事实"),
                    ("coverage", "覆盖"),
                    ("structure", "结构"),
                ]:
                    if dim_key in scores:
                        score_parts.append(f"{label} {scores[dim_key]:.1f}")
                score_str = " / ".join(score_parts) if score_parts else ""
                summary = f"🔬 评审完成: {score_str} (综合 {overall:.1f}/10)"
            else:
                summary = "🔬 评审完成"
            return ResearchStreamEvent(
                type="critic_score",
                data={
                    "summary": summary,
                    "scores": scores,
                    "overall": overall,
                    "scorer": "aggregate",
                    "name": name,
                },
            )

        if name.startswith("scorer_"):
            # Individual scorer completed — emit lightweight event for progress tracking
            scorer_label = _SCORER_DISPLAY_LABELS.get(
                name, name.replace("scorer_", "").replace("_", " ")
            )
            return ResearchStreamEvent(
                type="critic_score",
                data={
                    "scorer": name,
                    "summary": f"🔬 {scorer_label} 评分中...",
                    "scores": {},
                    "overall": 0.0,
                },
            )

        if name == "LangGraph":
            # Outermost graph completion: parent_ids is empty.
            # Critic subgraph also emits name="LangGraph" with non-empty
            # parent_ids — those are skipped.
            # We return None here; _stream_research detects this event itself
            # so it can attach the real request_id to the done payload.
            pass
    return None


def _is_root_done_event(ev: dict[str, Any]) -> bool:
    """Return True iff *ev* is the outermost LangGraph on_chain_end (done)."""
    return (
        ev.get("event") == "on_chain_end"
        and ev.get("name") == "LangGraph"
        and not (ev.get("parent_ids") or [])
    )


_RESEARCH_GRAPH_SINGLETON: Any = None
_RESEARCH_GRAPH_LOCK: asyncio.Lock | None = None

# In-memory cache of completed runs (request_id → InvestmentDueDiligenceReport dict)
# Required because MemorySaver doesn't persist to sqlite, so GET /research/{id}
# can't read past runs from the checkpoint DB.  Process restart loses cache.
# v0.8.5 D6 evaluation pipeline replaces this with proper sqlite persistence.
_RUN_RESULTS_CACHE: dict[str, dict[str, Any]] = {}


def _get_graph_lock() -> asyncio.Lock:
    """Return the module-level asyncio.Lock, creating it lazily inside the event loop."""
    global _RESEARCH_GRAPH_LOCK
    if _RESEARCH_GRAPH_LOCK is None:
        _RESEARCH_GRAPH_LOCK = asyncio.Lock()
    return _RESEARCH_GRAPH_LOCK


async def get_research_graph() -> Any:
    """Async DI factory: build the research graph singleton at first request (lazy init).

    Uses AsyncSqliteSaver so that graph.astream_events() works correctly in
    the async FastAPI event loop.  The singleton is built exactly once; subsequent
    calls return the cached instance without re-acquiring the lock.
    """
    global _RESEARCH_GRAPH_SINGLETON
    if _RESEARCH_GRAPH_SINGLETON is not None:
        return _RESEARCH_GRAPH_SINGLETON

    lock = _get_graph_lock()
    async with lock:
        # Double-checked locking: another coroutine may have built it while we waited.
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
        from app.agents.critic_subagents.plan_correctness_scorer import (
            PlanCorrectnessScorer,
        )
        from app.agents.critic_subagents.structure import StructureScorer
        from app.agents.data_collector import DataCollector
        from app.agents.research_planner import ResearchPlanner
        from app.agents.writer import Writer
        from app.orchestration.research_graph import build_research_graph
        from app.services.bocha_factory import build_bocha_service_from_env
        from app.services.kb_factory import build_kb_search_service_from_env
        from app.services.openai_client import build_llm_service_from_env
        from app.services.tushare_factory import build_tushare_service
        from app.tools.get_balance_sheet import GetBalanceSheetTool
        from app.tools.get_cashflow import GetCashflowTool
        from app.tools.get_daily_basic import GetDailyBasicTool
        from app.tools.get_dividend_history import GetDividendHistoryTool
        from app.tools.get_financials import GetFinancialsTool
        from app.tools.get_forecast import GetForecastTool
        from app.tools.get_holder_change import GetHolderChangeTool
        from app.tools.get_money_flow import GetMoneyFlowTool
        from app.tools.get_news import GetNewsTool
        from app.tools.get_pe_history import GetPeHistoryTool
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

        # v0.8.5 — 8 new tools per spec § 4.6
        registry.register(GetBalanceSheetTool(tushare=tushare))
        registry.register(GetCashflowTool(tushare=tushare))
        registry.register(GetDailyBasicTool(tushare=tushare))
        registry.register(GetPeHistoryTool(tushare=tushare))
        registry.register(GetForecastTool(tushare=tushare))
        registry.register(GetDividendHistoryTool(tushare=tushare))
        registry.register(GetHolderChangeTool(tushare=tushare))
        registry.register(GetMoneyFlowTool(tushare=tushare))

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
            PlanCorrectnessScorer(llm=llm),  # 第 7 scorer (v0.8.5)
        ]
        critic = Critic(llm=llm, scorers=scorers)

        # AsyncSqliteSaver hangs on graph.astream_events() in the production
        # event loop (root cause: aiosqlite worker thread starvation under
        # uvicorn ProactorEventLoop or async generator yield interaction).
        # langgraph integration tests pass because they run with their own
        # event loop policy. Until v0.8.5 D6 evaluation we use MemorySaver —
        # no sqlite persistence, but graph.astream_events works. Run history
        # is read directly from the deferred research.sqlite (which still
        # has past run data from before this switch).
        from langgraph.checkpoint.memory import MemorySaver

        _RESEARCH_GRAPH_SINGLETON = build_research_graph(
            planner=planner,
            collector=collector,
            analyst=analyst,
            writer=writer,
            critic=critic,
            checkpointer=MemorySaver(),
        )
        return _RESEARCH_GRAPH_SINGLETON


@router.post("/api/v0.5/research", deprecated=True)
async def research(
    req: ResearchRequest,
    user: _AnonUser = Depends(get_current_user),
    graph: Any = Depends(get_research_graph),
) -> StreamingResponse:
    """[DEPRECATED v0.9.x] use POST /reports → GET /reports/:id/stream instead.

    保留作为 alias,Task 9 align;v0.9.y 删除.

    POST /api/v0.5/research — stream a research report as SSE.

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
            # Stash writer output into in-memory cache so GET /research/{id} works
            # without sqlite persistence (MemorySaver workaround until v0.8.5).
            if ev.get("event") == "on_chain_end" and ev.get("name") == "writer_node":
                # LangGraph astream_events v2 places node return under
                # ev["data"]["output"]. Older paths used ev["output"]; check
                # both for forward/backward compatibility.
                output = ev.get("data", {}).get("output") or ev.get("output") or {}
                report_val = output.get("investment_report") if isinstance(output, dict) else None
                if report_val is not None:
                    if hasattr(report_val, "model_dump"):
                        _RUN_RESULTS_CACHE[request_id] = report_val.model_dump()
                    elif isinstance(report_val, dict):
                        _RUN_RESULTS_CACHE[request_id] = report_val
                    if request_id in _RUN_RESULTS_CACHE:
                        _RUN_RESULTS_CACHE[request_id]["request_id"] = request_id

            if _is_root_done_event(ev):
                # Emit done with the real backend request_id so the frontend
                # can navigate to the correct /research/<request_id> URL.
                done_evt = ResearchStreamEvent(type="done", data={"request_id": request_id})
                yield f"data: {done_evt.model_dump_json()}\n\n"
                continue
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

    Uses the SqliteSaver.list() API (not raw SQL) so we are immune to
    schema changes.  SqliteSaver.list(None) iterates all threads newest-first;
    we filter to threads whose thread_id starts with 'research:' and extract
    the 'investment_report' field from channel_values.

    Returns an empty list when the DB is absent or no research threads exist.
    Falls back to [] (not mock) — callers apply the mock fallback.

    TODO(Task 7 dogfood): replace mock fallback with proper error once we have
    real runs stored post-dogfood.
    """
    import sqlite3

    from langgraph.checkpoint.sqlite import SqliteSaver

    try:
        if not db_path.exists():
            return []

        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        saver = SqliteSaver(conn)

        results: list[ResearchRunSummary] = []
        seen_thread_ids: set[str] = set()

        # Materialize the generator BEFORE we iterate + break + close conn.
        # SqliteSaver.list() yields cursors that are still backed by `conn`;
        # if we break out of the loop and then close the conn, Python GC will
        # try to clean up the still-open generator's cursor on a closed db
        # and raise sqlite3.ProgrammingError.  Forcing list() consumes the
        # generator fully while conn is alive.
        checkpoints = list(saver.list(None, limit=limit * 10))  # over-fetch to get one per thread
        for ct in checkpoints:
            thread_id: str = ct.config.get("configurable", {}).get("thread_id", "")
            if not thread_id.startswith("research:"):
                continue
            if thread_id in seen_thread_ids:
                # Already captured the latest checkpoint for this thread.
                continue
            seen_thread_ids.add(thread_id)

            report = ct.checkpoint.get("channel_values", {}).get("investment_report")
            if report is None:
                continue

            try:
                # report is already a deserialized dict (SqliteSaver deserializes blobs).
                if not isinstance(report, dict):
                    report = report.model_dump() if hasattr(report, "model_dump") else {}
                request_id = str(report.get("request_id", thread_id))
                target_name = str(report.get("target_name", ""))
                target_ts_code = str(report.get("target_ts_code", ""))
                generated_at = str(report.get("generated_at", ""))
                rec = report.get("investment_recommendation") or {}
                if not isinstance(rec, dict):
                    rec = rec.model_dump() if hasattr(rec, "model_dump") else {}
                recommendation = str(rec.get("recommendation", ""))
                narrative = str(rec.get("narrative", ""))
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

            if len(results) >= limit:
                break

        conn.close()
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

    Lookup order:
      1. In-memory cache (this process's completed runs) — populated by
         _stream_research from writer_node output. MemorySaver doesn't
         persist to sqlite, so this cache is the primary source for runs
         completed in the current process.
      2. SqliteSaver.get_tuple() scan of past sqlite checkpoints — for runs
         from before the MemorySaver switch. Falls back to 404.

    TODO(Task 7 dogfood): consider exposing thread_id directly so we can skip
    the scan. v0.8.5 D6 evaluation pipeline replaces this with proper sqlite
    persistence so the cache becomes redundant.
    """
    # 1. Try in-memory cache first (current process's completed runs).
    cached = _RUN_RESULTS_CACHE.get(run_id)
    if cached is not None:
        return cached

    # 2. Fall back to sqlite checkpoint scan (past runs from before MemorySaver).
    db_path = Path("backend/data/research.sqlite")
    try:
        if db_path.exists():
            import sqlite3

            from langgraph.checkpoint.sqlite import SqliteSaver

            conn = sqlite3.connect(str(db_path), check_same_thread=False)
            saver = SqliteSaver(conn)

            # Strategy: scan all research threads for one whose thread_id
            # contains run_id or whose investment_report.request_id == run_id.
            # list(None) yields newest-first so the first hit is the latest.
            # Materialize generator to avoid sqlite3.ProgrammingError on early
            # return — see _read_research_runs_from_sqlite for the same fix.
            checkpoints = list(saver.list(None))
            try:
                for ct in checkpoints:
                    thread_id: str = ct.config.get("configurable", {}).get("thread_id", "")
                    if not thread_id.startswith("research:"):
                        continue

                    report = ct.checkpoint.get("channel_values", {}).get("investment_report")
                    if report is None:
                        continue

                    if not isinstance(report, dict):
                        report = report.model_dump() if hasattr(report, "model_dump") else {}

                    # Match by run_id in thread_id or in report.request_id.
                    if run_id in thread_id or str(report.get("request_id", "")) == run_id:
                        return report
            finally:
                conn.close()
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
