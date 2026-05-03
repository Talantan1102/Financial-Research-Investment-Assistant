"""L2 e2e — B-1 信贷尽调 茅台端到端 cassette (v0.8.2).

Records one full research pipeline run:
  ResearchPlanner → DataCollector (all stub tools — no tool HTTP)
  → Analyst → Writer (CreditInvestigationReport JSON schema)
  → Critic (x5) → credit_report_renderer

LLM:     DashScope post-pay endpoint (DASHSCOPE_API_KEY in backend/.env).
Tools:   All stub — no Milvus, no Bocha, no MockTushare HTTP calls.

Design note — why all stub tools (not real KB):
  Tools in DataCollector run via asyncio.gather (concurrent). VCR matches
  on method+scheme+host+port+path without body, so concurrent LLM calls
  to the same endpoint are consumed in arrival order. If MockTushare's LLM
  call arrives before the Analyst's LLM call, VCR returns the wrong
  cassette entry. Stub tools (returning hardcoded data) produce 0 tool
  HTTP calls, making the cassette sequence deterministic:
    [1] planner → [2] analyst → [3] writer → [4-8] 5 critics
  This is identical to test_research_agent_cassette.py's design choice.

  The credit report schema compliance (Writer + CreditInvestigationReport)
  is the primary value of this test. Real KB fidelity is tested separately
  in test_kb_search_cassette.py.
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from app.agents.analyst import Analyst
from app.agents.credit_report_schema import CreditInvestigationReport
from app.agents.critic import Critic
from app.agents.critic_subagents.conciseness import ConcisenessScorer
from app.agents.critic_subagents.coverage import CoverageScorer
from app.agents.critic_subagents.factuality import FactualityScorer
from app.agents.critic_subagents.insight import InsightScorer
from app.agents.critic_subagents.structure import StructureScorer
from app.agents.data_collector import DataCollector
from app.agents.research_planner import ResearchPlanner
from app.agents.schemas import ResearchState
from app.agents.writer import Writer
from app.orchestration.research_graph import build_research_graph
from app.services.openai_client import build_llm_service_from_env
from app.tools.base import Tool
from app.tools.registry import ToolRegistry
from pydantic import BaseModel, Field

pytestmark = pytest.mark.vcr


# ---------------------------------------------------------------------------
# Stub tools — hardcoded 茅台-relevant data; 0 HTTP calls per tool
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
            "revenue": 1.78e11,  # 1782亿元
            "net_profit": 8.57e10,  # 857亿元
            "roe": 0.335,  # 33.5%
            "gross_margin": 0.918,  # 91.8%
            "asset_liability_ratio": 0.18,
            "current_ratio": 4.2,
            "cash_and_equivalents": 1.5e11,  # 1500亿元
            "operating_cash_flow": 9.1e10,  # 910亿元
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
                    "snippet": "贵州茅台股份有限公司长期信用评级AAA,主体资格合规",
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
                    "chunk_id": "maotai_credit_profile::0",
                    "chunk_text": (
                        "贵州茅台酒股份有限公司统一社会信用代码:91520000230887934K。"
                        "注册资本125,619.78万元,实际控制人为贵州省国有资产监督管理委员会。"
                        "公司在上海证券交易所主板上市,股票代码600519.SH。"
                        "长期主体信用评级AAA,无重大不良记录。"
                    ),
                    "score": 0.92,
                    "metadata": {"source_type": "financial", "company_code": "600519"},
                },
                {
                    "chunk_id": "maotai_industry_analysis::0",
                    "chunk_text": (
                        "白酒行业2024年集中度持续提升,茅台市占率约15%,高端白酒竞争格局稳固。"
                        "主要竞争对手包括五粮液(000858.SZ)、泸州老窖(000568.SZ)。"
                        "国家政策对白酒行业实施总量控制,高端品牌受益于品牌壁垒。"
                        "白酒行业景气度高,茅台1935系列持续放量,系列酒贡献增量。"
                    ),
                    "score": 0.89,
                    "metadata": {"source_type": "research", "company_code": "600519"},
                },
            ]
        }


# ---------------------------------------------------------------------------
# VCR config override — drop body from match criteria for dynamic prompts
# ---------------------------------------------------------------------------


def _strip_dashscope_response_headers(response: dict[str, Any]) -> dict[str, Any]:
    """Remove DashScope-specific response headers before recording."""
    headers = response.get("headers", {})
    response["headers"] = {k: v for k, v in headers.items() if "dashscope" not in k.lower()}
    return response


@pytest.fixture(scope="module")
def vcr_config() -> dict[str, Any]:
    """Override module-level VCR config: drop body from match criteria.

    Agent prompts contain dynamic values (timestamps, latency_ms, chunk_ids).
    Match on method+scheme+host+port+path only (pipeline is deterministic).
    """
    return {
        "filter_headers": [
            "authorization",
            "x-dashscope-api-key",
            "x-api-key",
            "openai-organization",
        ],
        "filter_post_data_parameters": [],
        "decode_compressed_response": True,
        "record_mode": os.environ.get("VCR_RECORD_MODE", "none"),
        "match_on": ["method", "scheme", "host", "port", "path"],
        "before_record_response": _strip_dashscope_response_headers,
    }


# ---------------------------------------------------------------------------
# Build graph fixture — real LLM + all stub tools
# ---------------------------------------------------------------------------


@pytest.fixture
def b1_graph(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Build the research graph: real LLM (DashScope) + all stub tools.

    All tool calls return hardcoded 茅台-relevant data. This produces 0 tool
    HTTP calls, making the cassette sequence exactly:
      [1] planner LLM → [2] analyst LLM → [3] writer LLM → [4-8] 5 critic LLMs
    No Milvus/embedding/Bocha/MockTushare calls in cassette.
    """
    monkeypatch.setenv(
        "DASHSCOPE_API_KEY",
        os.environ.get("DASHSCOPE_API_KEY") or "sk-replay-placeholder",
    )

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
    ]
    critic = Critic(llm=llm, scorers=scorers)  # type: ignore[arg-type]

    return build_research_graph(
        planner=planner,
        collector=collector,
        analyst=analyst,
        writer=writer,
        critic=critic,
        db_path=None,  # stateless — no checkpointer for cassette
    )


# ---------------------------------------------------------------------------
# Cassette test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_b1_maotai_credit_report_e2e_cassette(b1_graph: Any) -> None:
    """B-1 端到端:输入茅台 + 信贷场景,产出符合 CreditInvestigationReport schema 的报告。

    Adaptation from plan:
      - Plan referenced build_research_pipeline_from_env() / pipeline.run() — these
        don't exist in the codebase. The actual entry is build_research_graph() +
        graph.ainvoke(state_dict, config). ResearchState is validated from the result
        dict via model_validate().
      - All tools replaced with stubs (no HTTP) to make cassette sequence deterministic.
        Concurrent tool execution in asyncio.gather + VCR body-less matching caused
        cassette entry misassignment. Stub tools eliminate all tool HTTP calls; the
        cassette contains exactly: planner + analyst + writer + 5 critics = 8 LLM calls.
      - No milvus_test_container fixture dependency; test runs without Milvus.
    """
    user_message = "评估贵州茅台(600519.SH)50 亿元 3 年期流动资金贷款。请输出完整信贷调查报告。"
    thread_id = "b1-maotai-test-1"
    initial = ResearchState(
        user_id="test",
        session_id=thread_id,
        user_message=user_message,
        request_id=thread_id,
    )
    config = {"configurable": {"thread_id": thread_id}}

    result = await b1_graph.ainvoke(initial.model_dump(), config=config)
    final_state = ResearchState.model_validate(result)

    # 1. State contains credit_report
    assert final_state.credit_report is not None, "Writer must produce a CreditInvestigationReport"
    report = final_state.credit_report
    assert isinstance(report, CreditInvestigationReport)

    # 2. company_name 锚定茅台
    assert "茅台" in report.company_name, (
        f"company_name must mention 茅台, got: {report.company_name!r}"
    )

    # 3. 6 sections all non-None (schema enforces required; this is a sanity check)
    assert report.company_overview is not None
    assert report.legal_qualification is not None
    assert report.financial_analysis is not None
    assert report.industry_analysis is not None
    assert report.risk_assessment is not None
    assert report.credit_recommendation is not None

    # 4. Evidence non-empty per section (schema min_length=1 enforces this too)
    assert len(report.company_overview.evidence) >= 1
    assert len(report.financial_analysis.evidence) >= 1
    assert len(report.credit_recommendation.evidence) >= 1

    # 5. decision is a valid enum value
    assert report.credit_recommendation.decision in {
        "approve",
        "reject",
        "approve_with_conditions",
    }

    # 6. markdown rendered and sufficiently long
    assert final_state.report_markdown is not None, "report_markdown must be set by writer_node"
    assert len(final_state.report_markdown) > 1500, (
        f"Markdown too short ({len(final_state.report_markdown)} chars); "
        "expected > 1500 chars for a 6-section credit report"
    )
    assert "# 信贷调查报告 — " in final_state.report_markdown, (
        "Markdown must begin with '# 信贷调查报告 — <company_name>' per renderer"
    )
