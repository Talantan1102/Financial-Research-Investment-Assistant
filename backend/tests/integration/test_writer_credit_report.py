"""L1 integration: Writer agent emits CreditInvestigationReport (v0.8.2)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import pytest
from app.agents.credit_report_schema import CreditInvestigationReport
from app.agents.schemas import Insight, ResearchState
from app.agents.writer import Writer
from app.services.llm_response import LLMResponse


class _StubLlm:
    """Returns a fixed schema-conformant CreditInvestigationReport JSON."""

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
        # auto-parse path (simulate v0.8.2 LLMService extension)
        if isinstance(schema, type) and issubclass(schema, CreditInvestigationReport):
            parsed = CreditInvestigationReport.model_validate_json(self.report_json)
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
            "company_name": "测试公司",
            "request_id": "will-be-overwritten",
            "generated_at": datetime(2026, 5, 3).isoformat(),
            "company_overview": {
                "narrative": "测试综述。",
                "main_business": "测试业务。",
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
                "solvency_analysis": "强。",
                "profitability_analysis": "稳定。",
                "cash_flow_analysis": "健康。",
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
                "operational_risks": [],
                "financial_risks": [],
                "industry_risks": [],
                "compliance_risks": [],
                "overall_risk_level": "low",
                "evidence": ["c1::4"],
            },
            "credit_recommendation": {
                "narrative": "建议批准。",
                "decision": "approve",
                "recommended_credit_limit": None,
                "recommended_term": None,
                "recommended_rate_range": None,
                "guarantee_requirements": [],
                "conditions": [],
                "evidence": ["c1::5"],
            },
        }
    )


def _state_with_insights() -> ResearchState:
    return ResearchState(
        request_id="req-test-write-001",
        user_id="u-test",
        session_id="s-test",
        user_message="评估贵州茅台 50 亿元 3 年期信贷",
        insights=[
            Insight(
                subtask_id="s1",
                finding="茅台营收 819 亿元",
                supporting_data=[],
                confidence="high",
            ),
        ],
    )


def test_writer_emits_credit_report(stub_report_json: str) -> None:
    state = _state_with_insights()
    writer = Writer(llm=_StubLlm(stub_report_json))  # type: ignore[arg-type]
    sr = writer.step(state)

    assert "credit_report" in sr.state_update
    report = sr.state_update["credit_report"]
    assert isinstance(report, CreditInvestigationReport)
    assert report.request_id == "req-test-write-001"  # writer overwrites
    assert report.credit_recommendation.decision == "approve"


def test_writer_passes_schema_to_llm(stub_report_json: str) -> None:
    """Writer must call LLMService.chat with schema=CreditInvestigationReport."""
    state = _state_with_insights()
    stub = _StubLlm(stub_report_json)
    writer = Writer(llm=stub)  # type: ignore[arg-type]
    writer.step(state)
    assert stub.last_schema is CreditInvestigationReport


def test_writer_renders_markdown(stub_report_json: str) -> None:
    state = _state_with_insights()
    writer = Writer(llm=_StubLlm(stub_report_json))  # type: ignore[arg-type]
    sr = writer.step(state)
    md = sr.state_update["report_markdown"]
    assert "# 信贷调查报告 — 测试公司" in md
    assert "## § 1 基本信息" in md
