"""L0 — research-mode I/O schemas."""

import pytest
from app.agents.schemas import (
    ChartSpec,
    CriticDimension,
    CriticDimensionScore,
    CriticReport,
    Insight,
    ResearchPlan,
    ResearchState,
    Subtask,
)
from pydantic import ValidationError


def test_subtask_minimal() -> None:
    s = Subtask(
        subtask_id="overview", description="x", required_tools=["get_stock_quote"], rationale="r"
    )
    assert s.subtask_id == "overview"


def test_research_plan_minimal() -> None:
    p = ResearchPlan(
        rationale="single subtask",
        subtasks=[
            Subtask(subtask_id="overview", description="x", required_tools=[], rationale="r")
        ],
    )
    assert len(p.subtasks) == 1


def test_research_plan_requires_subtasks() -> None:
    """v1.x — ResearchPlan requires ≥1 subtask (no more plan_id selector)."""
    with pytest.raises(ValidationError):
        ResearchPlan(rationale="r", subtasks=[])


def test_research_plan_rationale_max_length() -> None:
    """v1.x — rationale capped at 300 chars (was 200 in v0.8.5)."""
    with pytest.raises(ValidationError):
        ResearchPlan(
            rationale="x" * 301,
            subtasks=[Subtask(subtask_id="s", description="d", required_tools=[], rationale="r")],
        )


def test_insight_confidence_levels() -> None:
    from typing import Literal

    confidence_levels: tuple[Literal["high", "medium", "low"], ...] = ("high", "medium", "low")
    for c in confidence_levels:
        Insight(subtask_id="s", finding="f", supporting_data=[], confidence=c)


def test_critic_dimension_score_range() -> None:
    s = CriticDimensionScore(
        dimension="factuality", score=8.5, evidence="cite x", sub_agent_request_id="r"
    )
    assert s.score == 8.5


def test_critic_dimension_score_out_of_range_rejected() -> None:
    with pytest.raises(ValidationError):
        CriticDimensionScore(
            dimension="factuality", score=11.0, evidence="x", sub_agent_request_id="r"
        )


def test_critic_report_5_dims() -> None:
    dim_names: tuple[CriticDimension, ...] = (
        "factuality",
        "coverage",
        "insight",
        "structure",
        "conciseness",
    )
    dims = [
        CriticDimensionScore(dimension=d, score=8.0, evidence="e", sub_agent_request_id="r")
        for d in dim_names
    ]
    r = CriticReport(dimensions=dims, overall_score=8.0, summary_markdown="ok")
    assert len(r.dimensions) == 5


def test_chart_spec_minimal() -> None:
    c = ChartSpec(chart_id="c1", chart_type="line", title="t", data=[{"x": 1, "y": 2}])
    assert c.chart_type == "line"


def test_research_state_minimal() -> None:
    s = ResearchState(
        user_id="u",
        session_id="s",
        user_message="深度分析茅台",
        request_id="req-test1234",
    )
    assert s.plan is None
    assert s.tool_results == []
    assert s.report_markdown is None
    assert s.critic_report is None


def test_valuation_analysis_v1x_a5a_new_fields_default_none() -> None:
    """v1.x A5a: ValuationAnalysis 7 new fields default None, schema backward compat."""
    from app.agents.investment_dd_schema import ValuationAnalysis, ValuationModel

    va = ValuationAnalysis(
        narrative="test",
        industry_classification="白酒",
        active_models=[ValuationModel.PE, ValuationModel.DCF],
        valuation_consistency="consistent",
    )

    # New fields all default None
    assert va.pe_value is None
    assert va.pb_value is None
    assert va.ev_ebitda_value is None
    assert va.dcf_base is None
    assert va.dcf_bull is None
    assert va.dcf_bear is None
    assert va.dcf_sensitivity is None
    assert va.outlier_diagnosis is None
    assert va.router_override_reasoning is None

    # Backward compat: existing fields still work
    assert va.pe_historical_percentile is None


def test_outlier_diagnosis_schema_required_fields() -> None:
    from app.agents.investment_dd_schema import OutlierDiagnosis, ValuationModel

    od = OutlierDiagnosis(
        outlier_model=ValuationModel.DCF,
        likely_cause="永续增长率假设偏高",
        confidence="high",
        recommended_action="trust_consensus",
        narrative="DCF 给出 5000,其他 3 lens 给出 1500-1800,DCF 永续增长率 5% 偏离行业 2.5%。",
    )
    assert od.outlier_model == ValuationModel.DCF
    assert od.confidence == "high"


def test_critic_dimension_v1x_a5a_adds_valuation_consistency() -> None:
    from app.agents.schemas import CriticDimensionScore

    score = CriticDimensionScore(
        dimension="valuation_consistency",
        score=8.5,
        evidence="narrative reflects outlier diagnosis",
        sub_agent_request_id="req-001",
    )
    assert score.dimension == "valuation_consistency"


def test_valuation_analysis_active_models_max_length_4() -> None:
    """ValuationAnalysis.active_models 超过 4 个 → ValidationError."""
    from app.agents.investment_dd_schema import ValuationAnalysis, ValuationModel
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ValuationAnalysis(
            narrative="x",
            active_models=[  # 5 元素 — exceeds max_length=4
                ValuationModel.PE,
                ValuationModel.PB,
                ValuationModel.EV_EBITDA,
                ValuationModel.DCF,
                ValuationModel.PE,
            ],
        )


def test_outlier_diagnosis_is_frozen() -> None:
    """OutlierDiagnosis frozen=True → mutation 应 raise ValidationError."""
    from app.agents.investment_dd_schema import OutlierDiagnosis, ValuationModel
    from pydantic import ValidationError

    od = OutlierDiagnosis(
        outlier_model=ValuationModel.DCF,
        likely_cause="x",
        confidence="high",
        recommended_action="trust_consensus",
        narrative="x",
    )
    with pytest.raises(ValidationError):
        od.likely_cause = "modified"
