"""L0 — Writer prompt v1.x A5a cross-check block."""

from __future__ import annotations

from app.agents.investment_dd_schema import OutlierDiagnosis, ValuationAnalysis, ValuationModel
from app.agents.schemas import ResearchState


def _mk_state(valuation_analysis: ValuationAnalysis | None = None) -> ResearchState:
    return ResearchState(
        user_id="u",
        session_id="s",
        user_message="尽调茅台 600519.SH",
        request_id="r",
        target_ts_code="600519.SH",
        client_total_aum=50_000_000_000.0,
        investment_objective="balanced",
        investment_horizon="medium_term",
        risk_tolerance="moderate",
        valuation_analysis=valuation_analysis,
    )


def test_prompt_no_valuation_analysis_omits_cross_check_block() -> None:
    """valuation_analysis=None → prompt 不含 v1.x A5a cross-check 段落"""
    from app.agents.writer import build_investment_dd_prompt

    prompt = build_investment_dd_prompt(_mk_state(None))
    # Sentinel: 这个段落不该出现
    assert "v1.x A5a cross-check" not in prompt
    assert "outlier_diagnosis" not in prompt


def test_prompt_consistent_includes_consistency_mention_rule() -> None:
    """consistency=consistent → prompt 要求 narrative 提及一致性"""
    from app.agents.writer import build_investment_dd_prompt

    va = ValuationAnalysis(
        narrative="multi-model cross-check",
        industry_classification="白酒",
        active_models=[ValuationModel.PE, ValuationModel.DCF],
        pe_value=1500.0,
        dcf_base=1600.0,
        valuation_consistency="consistent",
    )
    prompt = build_investment_dd_prompt(_mk_state(va))
    assert "v1.x A5a cross-check" in prompt
    assert "consistent" in prompt or "一致" in prompt
    # 数字应该露在 prompt 里(LLM 才能引用)
    assert "1500" in prompt or "1,500" in prompt
    assert "1600" in prompt or "1,600" in prompt


def test_prompt_moderate_includes_explanation_requirement() -> None:
    """consistency=moderate → prompt 要求 narrative 解释偏离原因"""
    from app.agents.writer import build_investment_dd_prompt

    va = ValuationAnalysis(
        narrative="multi-model cross-check",
        industry_classification="白酒",
        active_models=[ValuationModel.PE, ValuationModel.DCF],
        pe_value=1200.0,
        dcf_base=1800.0,
        valuation_consistency="moderate",
    )
    prompt = build_investment_dd_prompt(_mk_state(va))
    assert "v1.x A5a cross-check" in prompt
    assert "偏离" in prompt or "差异" in prompt or "moderate" in prompt


def test_prompt_severe_with_diagnosis_includes_reference_requirement() -> None:
    """consistency=severe + diagnosis → prompt 要求 narrative 显式引用 diagnosis.narrative"""
    from app.agents.writer import build_investment_dd_prompt

    diagnosis = OutlierDiagnosis(
        outlier_model=ValuationModel.DCF,
        likely_cause="永续增长率偏高",
        confidence="high",
        recommended_action="trust_consensus",
        narrative="DCF 5000 偏离 PE 1500,主因永续增长率假设过乐观。",
    )
    va = ValuationAnalysis(
        narrative="multi-model cross-check",
        industry_classification="白酒",
        active_models=[ValuationModel.PE, ValuationModel.DCF],
        pe_value=1500.0,
        dcf_base=5000.0,
        valuation_consistency="severe",
        outlier_diagnosis=diagnosis,
    )
    prompt = build_investment_dd_prompt(_mk_state(va))
    assert "v1.x A5a cross-check" in prompt
    assert "severe" in prompt or "严重" in prompt
    # diagnosis.narrative 必须在 prompt 里,LLM 才能引用
    assert "DCF 5000 偏离 PE 1500,主因永续增长率假设过乐观。" in prompt
    # outlier_model + likely_cause + confidence 也应在 prompt 里(给 LLM context)
    assert "永续增长率偏高" in prompt
    assert "high" in prompt


def test_prompt_severe_without_diagnosis_includes_uncertainty_flag_rule() -> None:
    """consistency=severe + diagnosis=None(LLM 失败 fallback)→ prompt 要求 narrative flag 不确定"""
    from app.agents.writer import build_investment_dd_prompt

    va = ValuationAnalysis(
        narrative="multi-model cross-check",
        industry_classification="白酒",
        active_models=[ValuationModel.PE, ValuationModel.DCF],
        pe_value=500.0,
        dcf_base=2000.0,
        valuation_consistency="severe",
        outlier_diagnosis=None,
    )
    prompt = build_investment_dd_prompt(_mk_state(va))
    assert "v1.x A5a cross-check" in prompt
    assert "无法诊断" in prompt or "不确定" in prompt or "diagnosis 缺失" in prompt
