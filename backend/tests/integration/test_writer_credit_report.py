"""L1 integration: Writer agent emits InvestmentDueDiligenceReport (v0.8.4).

Replaces the former test_writer_credit_report.py (CreditInvestigationReport).
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import pytest
from app.agents.investment_dd_schema import InvestmentDueDiligenceReport
from app.agents.schemas import Insight, ResearchState
from app.agents.writer import Writer
from app.services.llm_response import LLMResponse


class _StubLlm:
    """Returns a fixed schema-conformant InvestmentDueDiligenceReport JSON."""

    def __init__(self, report_json: str) -> None:
        self.report_json = report_json
        self.last_schema: Any = None

    def chat(  # noqa: PLR0913
        self,
        prompt: str,
        tier: str = "balanced",
        schema: Any = None,
        request_id: str | None = None,
        parent_span_id: str | None = None,
    ) -> LLMResponse:
        self.last_schema = schema
        if isinstance(schema, type) and issubclass(schema, InvestmentDueDiligenceReport):
            parsed = InvestmentDueDiligenceReport.model_validate_json(self.report_json)
        else:
            parsed = None
        return LLMResponse(
            content=self.report_json,
            parsed=parsed,
            model="deepseek-v4-flash",
            tier="balanced",
            prompt_tokens=10,
            completion_tokens=200,
            total_tokens=210,
            cost_cny=0.001,
            latency_ms=100,
            request_id=request_id or "req-test",
        )


@pytest.fixture
def stub_report_json() -> str:
    return json.dumps(
        {
            "target_name": "测试公司",
            "target_ts_code": "000001.SZ",
            "request_id": "will-be-overwritten",
            "generated_at": datetime(2026, 5, 4).isoformat(),
            "target_close_price_at_gen": None,
            "target_market_cap_at_gen": None,
            "target_overview": {
                "narrative": "测试综述。",
                "registered_capital": None,
                "main_business": "测试业务。",
                "controlling_shareholder": None,
                "listing_status": None,
                "current_pe": None,
                "current_pb": None,
                "current_market_cap": None,
                "dividend_yield": None,
                "evidence": ["c1::0"],
            },
            "legal_qualification": {
                "narrative": "合规。",
                "legal_status": "正常",
                "business_qualifications": [],
                "adverse_records": [],
                "evidence": ["c1::1"],
            },
            "financial_analysis": {
                "narrative": "财务稳健。",
                "key_metrics": [
                    {"name": "营收", "value": "100", "period": "2024", "yoy_change": None}
                ],
                "profitability_analysis": "盈利能力稳定。",
                "growth_analysis": "成长性良好。",
                "return_analysis": "ROE 15%。",
                "cash_flow_analysis": "健康。",
                "valuation_analysis": {
                    "narrative": "估值合理。",
                    "pe_historical_percentile": None,
                    "dcf_valuation": None,
                    "peer_comparison": None,
                },
                "year_over_year_summary": None,
                "evidence": ["c1::2"],
            },
            "industry_analysis": {
                "narrative": "景气。",
                "industry_name": "X",
                "industry_outlook": "稳",
                "competitive_position": "前列",
                "key_competitors": [],
                "policy_impact": "无",
                "evidence": ["c1::3"],
            },
            "risk_assessment": {
                "narrative": "可控。",
                "market_risk": [],
                "growth_risk": [],
                "event_risk": [],
                "valuation_risk": [],
                "overall_risk_level": "low",
                "evidence": ["c1::4"],
            },
            "investment_recommendation": {
                "narrative": "建议增持。",
                "recommendation": "recommend_overweight",
                "recommended_position_size_pct": 5.0,
                "recommended_holding_period": "medium_term",
                "recommended_entry_price_range": {"low": 10.0, "high": 11.0},
                "recommended_stop_loss_price": 9.0,
                "estimated_target_price_range": {"low": 13.0, "high": 15.0},
                "position_management_conditions": [],
                "evidence": ["c1::5"],
            },
        }
    )


def _state_with_insights() -> ResearchState:
    return ResearchState(
        request_id="req-test-write-001",
        user_id="u-test",
        session_id="s-test",
        user_message="评估贵州茅台(600519.SH)投资价值",
        insights=[
            Insight(
                subtask_id="s1",
                finding="茅台营收 819 亿元",
                supporting_data=[],
                confidence="high",
            ),
        ],
    )


def test_writer_emits_investment_report(stub_report_json: str) -> None:
    state = _state_with_insights()
    writer = Writer(llm=_StubLlm(stub_report_json))  # type: ignore[arg-type]
    sr = writer.step(state)

    assert "investment_report" in sr.state_update
    report = sr.state_update["investment_report"]
    assert isinstance(report, InvestmentDueDiligenceReport)
    assert report.request_id == "req-test-write-001"  # writer overwrites
    assert report.investment_recommendation.recommendation == "recommend_overweight"


def test_writer_passes_schema_to_llm(stub_report_json: str) -> None:
    """Writer must call LLMService.chat with schema=InvestmentDueDiligenceReport."""
    state = _state_with_insights()
    stub = _StubLlm(stub_report_json)
    writer = Writer(llm=stub)  # type: ignore[arg-type]
    writer.step(state)
    assert stub.last_schema is InvestmentDueDiligenceReport


def test_writer_renders_markdown(stub_report_json: str) -> None:
    state = _state_with_insights()
    writer = Writer(llm=_StubLlm(stub_report_json))  # type: ignore[arg-type]
    sr = writer.step(state)
    md = sr.state_update["report_markdown"]
    assert "# 投资标的尽调报告 — 测试公司 (000001.SZ)" in md
    assert "## § 1 标的基本信息" in md
