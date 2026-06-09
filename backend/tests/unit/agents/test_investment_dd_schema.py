"""Unit tests for InvestmentDueDiligenceReport Pydantic schema (v0.8.4).

去推荐改造(2026-06-04):§ 6 InvestmentRecommendation → InvestmentSynthesis
(综合研判:多空两面 + 估值背景 + 关键判断变量,不下买卖结论)。
评级/仓位/目标价/止损位等 prescriptive 字段与对应测试已下线。
"""

from __future__ import annotations

import pytest
from app.agents.investment_dd_schema import (
    InvestmentDueDiligenceReport,
    InvestmentSynthesis,
    RiskAssessment,
    RiskItem,
    TargetOverview,
)
from pydantic import ValidationError


def test_investment_synthesis_two_sided_fields() -> None:
    """综合研判呈现多空两面 + 估值背景 + 关键判断变量,不含买卖评级。"""
    syn = InvestmentSynthesis(
        narrative="基本面稳健,估值处历史中低位;需关注高端需求与估值消化。",
        key_judgment_factors=["高端白酒需求景气度", "估值能否消化"],
        valuation_context="当前价位于内在价值区间下沿。",
        bull_case=["高端龙头护城河深", "现金流质量高"],
        bear_case=["估值对需求波动敏感"],
        strongest_bull_point="高端定价权稳",
        strongest_bear_point="需求若降速估值难撑",
        evidence=["chunk_001"],
    )
    assert syn.narrative
    assert syn.bull_case == ["高端龙头护城河深", "现金流质量高"]
    assert syn.bear_case == ["估值对需求波动敏感"]
    assert syn.key_judgment_factors == ["高端白酒需求景气度", "估值能否消化"]
    assert syn.valuation_context == "当前价位于内在价值区间下沿。"
    # 去推荐:综合研判里没有买卖评级 / 目标价 / 仓位字段
    assert not hasattr(syn, "recommendation")
    assert not hasattr(syn, "recommended_position_size_pct")
    assert not hasattr(syn, "estimated_target_price_range")


def test_investment_synthesis_optional_fields_default_empty() -> None:
    """只给 narrative 时,多空/判断变量/估值背景应默认空,不抛错。"""
    syn = InvestmentSynthesis(narrative="只有综述,其它留空。")
    assert syn.key_judgment_factors == []
    assert syn.bull_case == []
    assert syn.bear_case == []
    assert syn.valuation_context is None
    assert syn.strongest_bull_point is None
    assert syn.strongest_bear_point is None
    assert syn.evidence == []


def test_evidence_accepts_empty_list() -> None:
    """evidence 接受空 list — schema 软约束,Critic factuality 评分扣分代替强制。

    v0.8.4 dogfood revealed that mock KB data does not cover all 6 sections
    (legal_qualification / industry_analysis often empty). Strict min_length=1
    breaks the dogfood pipeline. Schema relaxed; Critic factuality scorer
    detects missing evidence and lowers the score instead.
    """
    syn = InvestmentSynthesis(
        narrative="综合研判综述。",
        evidence=[],  # ← schema accepts empty; Critic scorer handles
    )
    assert syn.evidence == []


def test_main_report_has_disclaimer_field() -> None:
    """主报告必须含 disclaimer 字段(默认值非空)。"""
    from tests.fixtures.investment_dd_fixtures import minimal_valid_report

    report = minimal_valid_report()
    assert report.disclaimer
    assert "AI 模型" in report.disclaimer
    assert "辅助生成" in report.disclaimer
    assert "投资决策" in report.disclaimer


def test_minimal_valid_report() -> None:
    from tests.fixtures.investment_dd_fixtures import minimal_valid_report

    r = minimal_valid_report()
    assert r.target_name == "贵州茅台酒股份有限公司"
    # 去推荐:主报告字段为 investment_synthesis,呈现综合研判 narrative
    assert r.investment_synthesis.narrative
    assert r.investment_synthesis.bull_case


def test_overall_risk_level_enum_strict() -> None:
    with pytest.raises(ValidationError):
        RiskAssessment(
            narrative="x",
            market_risk=[],
            growth_risk=[],
            event_risk=[],
            valuation_risk=[],
            overall_risk_level="catastrophic",  # type: ignore[arg-type]
            evidence=["c1::0"],
        )


def test_risk_item_severity_enum_strict() -> None:
    with pytest.raises(ValidationError):
        RiskItem(
            title="x",
            description="y",
            severity="moderate",  # type: ignore[arg-type]
        )


def test_required_field_missing_rejected() -> None:
    """target_overview 缺 main_business 必拒。"""
    with pytest.raises(ValidationError):
        TargetOverview(narrative="x", evidence=["c1::0"])  # type: ignore[call-arg]


def test_json_roundtrip() -> None:
    from tests.fixtures.investment_dd_fixtures import minimal_valid_report

    r = minimal_valid_report()
    j = r.model_dump_json()
    r2 = InvestmentDueDiligenceReport.model_validate_json(j)
    assert r2 == r


def test_json_schema_generation() -> None:
    """`model_json_schema()` 不抛异常,作为 LLMService.chat schema= 入参形态。"""
    schema = InvestmentDueDiligenceReport.model_json_schema()
    assert schema["type"] == "object"
    assert "target_name" in schema["properties"]


def test_empty_evidence_in_target_overview_accepted() -> None:
    """TargetOverview evidence 允许空(同上,软约束 + Critic 评分扣分)。"""
    overview = TargetOverview(narrative="x", main_business="y", evidence=[])
    assert overview.evidence == []


def test_investment_report_target_ts_code_stored() -> None:
    """target_ts_code 字段存储并可查询。"""
    from tests.fixtures.investment_dd_fixtures import minimal_valid_report

    r = minimal_valid_report()
    assert r.target_ts_code == "600519.SH"


def test_risk_assessment_optional_risk_items_default_empty() -> None:
    """market_risk / growth_risk / event_risk / valuation_risk 可为空列表。"""
    ra = RiskAssessment(
        narrative="低风险",
        market_risk=[],
        growth_risk=[],
        event_risk=[],
        valuation_risk=[],
        overall_risk_level="low",
        evidence=["c1::0"],
    )
    assert ra.market_risk == []
    assert ra.overall_risk_level == "low"
