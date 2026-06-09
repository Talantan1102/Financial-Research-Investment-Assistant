"""DDReportPipelineAdapter — 把生产 ResearchAgent 包成 PipelineProtocol."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest
from app.agents.investment_dd_schema import (
    DEFAULT_DISCLAIMER,
    FinancialAnalysis,
    IndustryAnalysis,
    InvestmentDueDiligenceReport,
    InvestmentSynthesis,
    LegalQualification,
    RiskAssessment,
    TargetOverview,
    ValuationAnalysis,
)
from eval.dd_report.pipeline_adapter import DDReportPipelineAdapter


def _make_fake_report(target_name: str, target_ts_code: str) -> InvestmentDueDiligenceReport:
    return InvestmentDueDiligenceReport(
        target_name=target_name,
        target_ts_code=target_ts_code,
        request_id="req-test",
        generated_at=datetime.now(UTC),
        target_close_price_at_gen=1500.0,
        target_overview=TargetOverview(narrative="...", main_business="白酒"),
        legal_qualification=LegalQualification(
            narrative="...",
            legal_status="合规",
            business_qualifications=[],
            adverse_records=[],
        ),
        financial_analysis=FinancialAnalysis(
            narrative="...",
            key_metrics=[],
            profitability_analysis="...",
            growth_analysis="...",
            return_analysis="...",
            cash_flow_analysis="...",
            valuation_analysis=ValuationAnalysis(narrative="..."),
        ),
        industry_analysis=IndustryAnalysis(
            narrative="...",
            industry_name="白酒",
            industry_outlook="...",
            competitive_position="...",
            key_competitors=[],
            policy_impact="...",
        ),
        risk_assessment=RiskAssessment(
            narrative="...",
            market_risk=[],
            growth_risk=[],
            event_risk=[],
            valuation_risk=[],
            overall_risk_level="medium",
        ),
        investment_synthesis=InvestmentSynthesis(
            narrative="综合研判综述",
            key_judgment_factors=[],
            bull_case=[],
            bear_case=[],
        ),
    )


def test_adapter_runs_pipeline_and_returns_report_dict() -> None:
    """适配器接受 mock production pipeline factory, 返回 dict(InvestmentDueDiligenceReport)."""
    captured_kwargs: dict[str, Any] = {}
    fake_report = _make_fake_report("茅台", "600519.SH")

    def fake_pipeline_factory(
        *, tushare_adapter: Any, kb_adapter: Any, evaluator_client: Any
    ) -> Any:
        def runner(target_name: str, target_ts_code: str) -> InvestmentDueDiligenceReport:
            captured_kwargs["target_name"] = target_name
            captured_kwargs["target_ts_code"] = target_ts_code
            captured_kwargs["tushare_adapter"] = tushare_adapter
            captured_kwargs["kb_adapter"] = kb_adapter
            captured_kwargs["evaluator_client"] = evaluator_client
            return fake_report

        return runner

    adapter = DDReportPipelineAdapter(pipeline_factory=fake_pipeline_factory)
    out = adapter.run(
        target_name="茅台",
        ts_code="600519.SH",
        tushare_adapter=MagicMock(),
        kb_adapter=MagicMock(),
        evaluator_client=MagicMock(),
    )
    assert isinstance(out, dict)
    assert out["target_name"] == "茅台"
    assert out["target_ts_code"] == "600519.SH"
    assert out["disclaimer"] == DEFAULT_DISCLAIMER
    assert captured_kwargs["target_name"] == "茅台"
    assert captured_kwargs["evaluator_client"] is not None
    assert captured_kwargs["target_ts_code"] == "600519.SH"
    assert captured_kwargs["tushare_adapter"] is not None
    assert captured_kwargs["kb_adapter"] is not None


def test_adapter_raises_when_pipeline_returns_wrong_type() -> None:
    def bad_factory(*, tushare_adapter: Any, kb_adapter: Any, evaluator_client: Any) -> Any:
        def runner(target_name: str, target_ts_code: str) -> str:
            return "not a report"

        return runner

    adapter = DDReportPipelineAdapter(pipeline_factory=bad_factory)
    with pytest.raises(TypeError, match="expected InvestmentDueDiligenceReport"):
        adapter.run(
            target_name="X",
            ts_code="X.SH",
            tushare_adapter=MagicMock(),
            kb_adapter=MagicMock(),
            evaluator_client=MagicMock(),
        )
