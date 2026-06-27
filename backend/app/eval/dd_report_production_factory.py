"""Production DD report pipeline factory for eval framework.

Bridges production ResearchAgent (`app/orchestration/research_graph.py`) into
the eval `_PipelineFactoryProtocol` (T2.8).

Phase 2 real wiring:
  - Builds 5 agents + 7 scorers + Critic using build_llm_service_from_env()
  - Wraps TushareBacktestAdapter → async TushareService via _BacktestTushareService
  - Wraps KBBacktestAdapter → async KbSearchService via _BacktestKbService
  - Calls build_research_graph(...) with MemorySaver()
  - Runner calls asyncio.run(graph.ainvoke(initial_state)) synchronously
  - V3 ablation: NoOpCritic (no scorers, always approve)
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pandas as pd

# Re-export judge wrappers (T2.2 / T2.4 ship the actual classes; here we just expose them
# under app.eval namespace for T2.11 dogfood script convenience).
from eval.dd_report.metrics.citation_metric import EvaluatorJudge as _EvalJudge
from eval.dd_report.metrics.risk_pairing_metric import EvaluatorPairingJudge as _EvalPairing


def build_supports_judge(client: Any) -> _EvalJudge:
    """Wrap an EvaluatorClient into the M1 SupportsJudgeProtocol."""
    return _EvalJudge(client)


def build_pairing_judge(client: Any) -> _EvalPairing:
    """Wrap an EvaluatorClient into the M3 PairingJudgeProtocol."""
    return _EvalPairing(client)


# ---------------------------------------------------------------------------
# Backtest adapter → Production protocol bridges
# ---------------------------------------------------------------------------


class _BacktestTushareService:
    """Wraps TushareBacktestAdapter to expose the async TushareService protocol.

    TushareBacktestAdapter has sync fetch_income / fetch_balancesheet / fetch_cashflow /
    fetch_daily_kline / fetch_announcements methods that return list[dict].

    Production tools (GetFinancialsTool etc.) call async get_income / get_daily / etc.
    returning pd.DataFrame.

    This bridge makes BacktestAdapter usable directly as TushareService dep injection
    for the production tool registry.
    """

    def __init__(self, adapter: Any) -> None:
        self._a = adapter  # TushareBacktestAdapter

    # --- helpers ---

    @staticmethod
    def _rows_to_df(rows: list[dict[str, Any]]) -> pd.DataFrame:
        return pd.DataFrame(rows) if rows else pd.DataFrame()

    # --- TushareService protocol (async, returns pd.DataFrame) ---

    async def get_daily(self, *, ts_code: str, start: str, end: str) -> pd.DataFrame:
        rows = self._a.fetch_daily_kline(ts_code, start_date=start)
        return self._rows_to_df(rows)

    async def get_income(self, *, ts_code: str, end_date: str | None = None) -> pd.DataFrame:
        rows = self._a.fetch_income(ts_code)
        return self._rows_to_df(rows)

    async def get_fina_indicator(
        self, *, ts_code: str, end_date: str | None = None
    ) -> pd.DataFrame:
        # TushareBacktestAdapter does not have a fina_indicator endpoint;
        # return empty DataFrame — tools handle empty gracefully.
        return pd.DataFrame()

    async def get_balance_sheet(self, *, ts_code: str, end_date: str | None = None) -> pd.DataFrame:
        rows = self._a.fetch_balancesheet(ts_code)
        return self._rows_to_df(rows)

    async def get_cashflow(self, *, ts_code: str, end_date: str | None = None) -> pd.DataFrame:
        rows = self._a.fetch_cashflow(ts_code)
        return self._rows_to_df(rows)

    async def get_stk_holdernumber(
        self, *, ts_code: str, end_date: str | None = None
    ) -> pd.DataFrame:
        return pd.DataFrame()

    async def get_disclosure_date(
        self, *, ts_code: str | None, start: str, end: str
    ) -> pd.DataFrame:
        return pd.DataFrame()

    async def get_anns(self, *, ts_code: str, start: str, end: str) -> pd.DataFrame:
        rows = self._a.fetch_announcements(ts_code)
        return self._rows_to_df(rows)

    # v0.8.5 extended interface
    async def get_daily_basic(
        self,
        *,
        ts_code: str,
        trade_date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        return pd.DataFrame()

    async def get_pe_history(
        self,
        *,
        ts_code: str,
        years_back: int = 5,
        current_pe: float | None = None,
        as_of: str | None = None,
    ) -> pd.DataFrame:
        return pd.DataFrame()

    async def get_forecast(self, *, ts_code: str, period: str | None = None) -> pd.DataFrame:
        return pd.DataFrame()

    async def get_dividend_history(self, *, ts_code: str, years_back: int = 5) -> pd.DataFrame:
        return pd.DataFrame()

    async def get_holder_change(self, *, ts_code: str, years_back: int = 2) -> pd.DataFrame:
        return pd.DataFrame()

    async def get_money_flow(self, *, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return pd.DataFrame()

    # 持仓总览新增的取数方法 — 回测适配器不提供市场/基金/板块数据,返回空
    async def get_index_daily(
        self, *, ts_code: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        return pd.DataFrame()

    async def get_fund_nav(self, *, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return pd.DataFrame()

    async def get_fund_basic(self, *, ts_code: str) -> pd.DataFrame:
        return pd.DataFrame()

    async def get_stock_basic(self, *, ts_code: str | None = None) -> pd.DataFrame:
        return pd.DataFrame()

    async def get_index_weight(
        self,
        *,
        index_code: str,
        trade_date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        return pd.DataFrame()

    async def get_sw_index_daily(self, *, index_code: str, trade_date: str) -> pd.DataFrame:
        return pd.DataFrame()

    async def get_trade_cal(self, *, start: str, end: str) -> pd.DataFrame:
        return pd.DataFrame()

    async def aclose(self) -> None:
        pass


class _BacktestKbService:
    """Wraps KBBacktestAdapter to expose the async KbSearchService protocol.

    KBBacktestAdapter.search(query, k, **kwargs) → list[Any]
    KbSearchService.search(query, collections, top_k, threshold, filters) → list[KbHit]

    The KBBacktestAdapter inner is usually MockKbSearchService or a stub.
    Its results may be KbHit objects or plain dicts — we normalise into KbHit.
    """

    def __init__(self, adapter: Any) -> None:
        self._a = adapter  # KBBacktestAdapter

    async def search(
        self,
        query: str,
        collections: list[str] | None = None,
        top_k: int = 5,
        threshold: float | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[Any]:
        from app.services.kb_search_service import KbHit

        raw = self._a.search(query=query, k=top_k)
        hits: list[KbHit] = []
        for item in raw:
            if isinstance(item, KbHit):
                hits.append(item)
            elif isinstance(item, dict):
                hits.append(
                    KbHit(
                        chunk_id=str(item.get("chunk_id", "")),
                        chunk_text=str(item.get("chunk_text", "")),
                        similarity=float(item.get("similarity", 1.0)),
                        metadata={
                            k: v
                            for k, v in item.items()
                            if k not in ("chunk_id", "chunk_text", "similarity")
                        },
                    )
                )
            else:
                # C42: unknown type is a programming/adapter error; fail loud so
                # corrupted ablation metrics surface immediately (Rule 4).
                raise TypeError(
                    f"_BacktestKbService: unexpected KB adapter result type"
                    f" {type(item).__name__!r}: {item!r}"
                )
        return hits


# ---------------------------------------------------------------------------
# NoOpCritic for V3 ablation
# ---------------------------------------------------------------------------


def _build_noop_critic(llm: Any) -> Any:
    """Build a Critic with no scorers that always returns approve (overall=10).

    Used for V3 (no_critic) ablation: the graph still runs through critic_node
    but gets an immediate full-score approve, so the retry router never fires
    and the report is returned as-is without critic iteration.
    """
    from app.agents.critic import Critic
    from app.agents.schemas import CriticReport

    class _NoOpCritic(Critic):
        """Critic that always returns a full-approval CriticReport with no scorers.

        Also overrides dispatch_subagent to return an empty StepResult for every
        scorer name — the critic_subgraph sends to 7 hardcoded nodes each of which
        calls dispatch_subagent(name=...). Without this override the KeyError from
        Critic.dispatch_subagent would surface as a run failure in V3 ablation.
        """

        def __init__(self, llm: Any) -> None:
            super().__init__(llm=llm, scorers=[])

        def step(self, state: Any) -> Any:
            from app.agents.schemas import StepResult

            report = CriticReport(
                dimensions=[],
                overall_score=10.0,
                summary_markdown="(NoOpCritic — V3 ablation: critic disabled)",
            )
            return StepResult(
                state_update={"critic_report": report},
                span_metadata={"agent": "NoOpCritic"},
            )

        def dispatch_subagent(self, name: str, state: Any) -> Any:
            """Accept any scorer name; return empty StepResult (no score collected)."""
            from app.agents.schemas import StepResult

            return StepResult(
                state_update={},
                span_metadata={"agent": "NoOpCritic", "scorer": name},
            )

        async def astep(self, state: Any) -> Any:  # noqa: ANN401 — async mirror
            return self.step(state)

    return _NoOpCritic(llm=llm)


# ---------------------------------------------------------------------------
# Production graph runner
# ---------------------------------------------------------------------------


def _build_production_runner(
    *,
    tushare_adapter: Any,
    kb_adapter: Any,
    disable_critic: bool = False,
) -> Any:
    """Build production 5-agent LangGraph runner with backtest adapters wired in.

    Returns a callable (target_name, target_ts_code) → InvestmentDueDiligenceReport.
    """
    from langgraph.checkpoint.memory import MemorySaver

    from app.agents.analyst import Analyst
    from app.agents.critic import Critic
    from app.agents.critic_subagents.conciseness import ConcisenessScorer
    from app.agents.critic_subagents.coverage import CoverageScorer
    from app.agents.critic_subagents.factuality import FactualityScorer
    from app.agents.critic_subagents.input_context_scorer import (
        InputContextAppropriatenessScorer,
    )
    from app.agents.critic_subagents.insight import InsightScorer
    from app.agents.critic_subagents.plan_correctness_scorer import PlanCorrectnessScorer
    from app.agents.critic_subagents.structure import StructureScorer
    from app.agents.data_collector import DataCollector
    from app.agents.research_planner import ResearchPlanner
    from app.agents.schemas import ResearchState
    from app.agents.writer import Writer
    from app.orchestration.research_graph import build_research_graph
    from app.services.bocha_factory import build_bocha_service_from_env
    from app.services.openai_client import build_llm_service_from_env
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

    # Wrap backtest adapters into production protocol shapes
    tushare_service = _BacktestTushareService(tushare_adapter)
    kb_service = _BacktestKbService(kb_adapter)

    # Build tool registry using backtest-aware wrappers
    registry = ToolRegistry()
    registry.register(StockQuoteTool(tushare=tushare_service))
    registry.register(GetFinancialsTool(tushare=tushare_service))
    registry.register(GetBalanceSheetTool(tushare=tushare_service))
    registry.register(GetCashflowTool(tushare=tushare_service))
    registry.register(GetDailyBasicTool(tushare=tushare_service))
    registry.register(GetPeHistoryTool(tushare=tushare_service))
    registry.register(GetForecastTool(tushare=tushare_service))
    registry.register(GetDividendHistoryTool(tushare=tushare_service))
    registry.register(GetHolderChangeTool(tushare=tushare_service))
    registry.register(GetMoneyFlowTool(tushare=tushare_service))
    # Bocha / web search: use env-driven mock (no cut_off contamination risk)
    bocha = build_bocha_service_from_env()
    registry.register(GetNewsTool(bocha=bocha))
    registry.register(WebSearchTool(bocha=bocha))
    registry.register(KbSearchTool(kb_service=kb_service))
    # Build agents
    planner = ResearchPlanner(llm=llm)
    collector = DataCollector(llm=llm, registry=registry)
    analyst = Analyst(llm=llm)
    writer = Writer(llm=llm)

    if disable_critic:
        critic = _build_noop_critic(llm=llm)
    else:
        scorers = [
            FactualityScorer(llm=llm),
            CoverageScorer(llm=llm),
            InsightScorer(llm=llm),
            StructureScorer(llm=llm),
            ConcisenessScorer(llm=llm),
            InputContextAppropriatenessScorer(llm=llm),
            PlanCorrectnessScorer(llm=llm),
        ]
        critic = Critic(llm=llm, scorers=scorers)

    graph = build_research_graph(
        planner=planner,
        collector=collector,
        analyst=analyst,
        writer=writer,
        critic=critic,
        checkpointer=MemorySaver(),
    )

    def runner(target_name: str, target_ts_code: str) -> Any:
        """Run graph synchronously, return InvestmentDueDiligenceReport."""
        request_id = f"backtest-{uuid.uuid4().hex[:12]}"
        initial = ResearchState(
            user_id="backtest-eval",
            session_id=request_id,
            user_message=f"请对 {target_name} ({target_ts_code}) 进行投资标的尽调。",
            request_id=request_id,
            target_ts_code=target_ts_code,
            # Defaults: balanced/medium_term/balanced as generic backtest persona
            client_total_aum=1_000_000.0,
            investment_objective="balanced",
            investment_horizon="medium_term",
            risk_tolerance="balanced",
        )
        config = {"configurable": {"thread_id": f"backtest:{request_id}"}}

        final_state: Any = asyncio.run(graph.ainvoke(initial.model_dump(), config=config))

        # final_state may be dict or ResearchState depending on LangGraph version
        if isinstance(final_state, dict):
            report = final_state.get("investment_report")
        else:
            report = getattr(final_state, "investment_report", None)

        if report is None:
            from eval.dd_report.ablation.null_adapters import _minimal_stub

            return _minimal_stub(target_name, target_ts_code)

        return report

    return runner


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------


def build_dd_report_production_factory() -> Any:
    """Return a `production_factory` callable matching `_PipelineFactoryProtocol`.

    Returned factory signature (per T2.8 _PipelineFactoryProtocol):
        (*, tushare_adapter, kb_adapter, evaluator_client, disable_critic=False) -> runner

    Real production wire:
      - Builds full 5-agent LangGraph with backtest adapters wired as TushareService
        and KbSearchService
      - V3 ablation uses NoOpCritic (scorer-less, always approve)
      - evaluator_client is accepted for protocol compatibility but unused by the
        production graph (which uses its own LLM from build_llm_service_from_env)
    """

    def production_factory(
        *,
        tushare_adapter: Any,
        kb_adapter: Any,
        evaluator_client: Any,
        disable_critic: bool = False,
    ) -> Any:
        # evaluator_client accepted for protocol compat but unused:
        # production graph builds its own LLM from env
        del evaluator_client
        return _build_production_runner(
            tushare_adapter=tushare_adapter,
            kb_adapter=kb_adapter,
            disable_critic=disable_critic,
        )

    return production_factory
