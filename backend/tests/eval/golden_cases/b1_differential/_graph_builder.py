"""Shared graph builder for B-1 differential golden case tests.

Builds a research graph with:
  - Real LLM (DashScope via build_llm_service_from_env)
  - All stub tools (identical to test_b1_maotai_investment_dd_cassette.py)
  - 6 Critic scorers including InputContextAppropriatenessScorer
  - No checkpointer (stateless, cassette-safe)

Cassette sequence (deterministic, same as e2e B1 cassette):
  [1] planner LLM
  [2] analyst LLM
  [3] writer LLM
  [4-9] 6 critic LLMs (factuality / coverage / insight / structure / conciseness / input_context)

The 6th LLM call is the new InputContextAppropriatenessScorer judge call.
"""

from __future__ import annotations

import os
from typing import Any

import pytest
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
from app.services.openai_client import build_llm_service_from_env
from app.tools.base import Tool
from app.tools.registry import ToolRegistry
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Stub tools — hardcoded 茅台-relevant data; identical to e2e cassette test
# ---------------------------------------------------------------------------


class _StubQuoteArgs(BaseModel):
    ts_code: str


class _StubQuoteTool(Tool):
    name = "get_stock_quote"
    description = "Return stock quote (stub)."
    args_schema = _StubQuoteArgs

    async def run(self, args: BaseModel) -> dict[str, Any]:
        return {
            "ts_code": "600519.SH",
            "price": 1748.50,
            "change_pct": 0.38,
            "volume": 8432.0,
            "market_cap": "22000亿元",
        }


class _StubFinancialsArgs(BaseModel):
    ts_code: str
    period: str = "latest"


class _StubFinancialsTool(Tool):
    name = "get_financials"
    description = "Return financials (stub)."
    args_schema = _StubFinancialsArgs

    async def run(self, args: BaseModel) -> dict[str, Any]:
        return {
            "ts_code": "600519.SH",
            "period": "2024",
            "revenue": 1.78e11,
            "net_profit": 8.57e10,
            "roe": 0.335,
            "gross_margin": 0.918,
            "asset_liability_ratio": 0.18,
            "current_ratio": 4.2,
            "cash_and_equivalents": 1.5e11,
            "operating_cash_flow": 9.1e10,
        }


class _StubNewsArgs(BaseModel):
    ts_code: str | None = None
    n: int = Field(default=5, ge=1)
    days_back: int = Field(default=7, ge=1)


class _StubNewsTool(Tool):
    name = "get_news"
    description = "Return news (stub)."
    args_schema = _StubNewsArgs

    async def run(self, args: BaseModel) -> dict[str, Any]:
        return {
            "items": [
                {
                    "title": "贵州茅台2024年报:营收1782亿元,净利857亿元",
                    "summary": "茅台2024年业绩创历史新高,股息率约2%",
                    "date": "2025-03-28",
                },
                {
                    "title": "白酒行业景气度持续,头部品牌量价齐升",
                    "summary": "高端白酒需求稳健,茅台量价齐升格局延续",
                    "date": "2025-04-05",
                },
            ]
        }


class _StubWebSearchArgs(BaseModel):
    query: str
    search_type: str = "news"
    count: int = Field(default=5, ge=1, le=20)


class _StubWebSearchTool(Tool):
    name = "web_search"
    description = "Web search (stub)."
    args_schema = _StubWebSearchArgs

    async def run(self, args: BaseModel) -> dict[str, Any]:
        return {
            "items": [
                {
                    "title": "茅台信用评级:AAA级",
                    "url": "https://example.com/1",
                    "snippet": "贵州茅台股份有限公司长期主体评级AAA,合规",
                },
                {
                    "title": "白酒行业监管:符合国家产业政策",
                    "url": "https://example.com/2",
                    "snippet": "茅台酿酒业属于国家鼓励类产业,享有相关税收优惠政策",
                },
            ]
        }


class _StubKbSearchArgs(BaseModel):
    query: str
    top_k: int = Field(default=5, ge=1, le=20)


class _StubKbSearchTool(Tool):
    name = "kb_search"
    description = "KB search (stub — 茅台财报数据)."
    args_schema = _StubKbSearchArgs

    async def run(self, args: BaseModel) -> dict[str, Any]:
        return {
            "items": [
                {
                    "chunk_id": "maotai_2024_annual_report::0",
                    "chunk_text": (
                        "贵州茅台酒股份有限公司2024年实现营业收入1782亿元,同比增长15.4%;"
                        "归属于上市公司股东净利润857亿元,同比增长14.8%。"
                        "公司资产负债率约为18%,流动比率4.2,货币资金1500亿元,"
                        "经营性现金流净额910亿元。"
                    ),
                    "score": 0.95,
                    "metadata": {"source_type": "financial", "company_code": "600519"},
                },
                {
                    "chunk_id": "maotai_investment_profile::0",
                    "chunk_text": (
                        "贵州茅台酒股份有限公司(600519.SH)注册资本125,619.78万元,"
                        "实际控制人为贵州省国有资产监督管理委员会。"
                        "长期主体信用评级AAA,无重大不良记录。"
                    ),
                    "score": 0.92,
                    "metadata": {"source_type": "financial", "company_code": "600519"},
                },
                {
                    "chunk_id": "maotai_industry_analysis::0",
                    "chunk_text": (
                        "白酒行业2024年集中度持续提升,茅台市占率约15%,高端白酒竞争格局稳固。"
                        "白酒行业景气度高,茅台1935系列持续放量,系列酒贡献增量。"
                    ),
                    "score": 0.89,
                    "metadata": {"source_type": "research", "company_code": "600519"},
                },
            ]
        }


# ---------------------------------------------------------------------------
# Graph builder — public API
# ---------------------------------------------------------------------------


def build_b1_diff_graph(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Build the research graph with 6 scorers for differential golden case tests.

    Args:
        monkeypatch: pytest monkeypatch fixture for env var injection.

    Returns:
        Compiled LangGraph ready for .ainvoke(initial_state, config=config).
    """
    monkeypatch.setenv(
        "DASHSCOPE_API_KEY",
        os.environ.get("DASHSCOPE_API_KEY") or "sk-replay-placeholder",
    )
    monkeypatch.setenv("LLM_MODE", "cassette")

    llm = build_llm_service_from_env()

    registry = ToolRegistry()
    registry.register(_StubQuoteTool())
    registry.register(_StubFinancialsTool())
    registry.register(_StubNewsTool())
    registry.register(_StubWebSearchTool())
    registry.register(_StubKbSearchTool())

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
        InputContextAppropriatenessScorer(llm=llm),  # 第 6 scorer
        # v1.x: PlanCorrectnessScorer removed (Task 1.5). Critic now runs 6 scorers.
    ]
    critic = Critic(llm=llm, scorers=scorers)

    return build_research_graph(
        planner=planner,
        collector=collector,
        analyst=analyst,
        writer=writer,
        critic=critic,
        db_path=None,  # stateless — no checkpointer for cassette
    )
