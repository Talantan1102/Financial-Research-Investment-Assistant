"""L0 — Critic 7th dim valuation_consistency rule-based scorer."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.agents.investment_dd_schema import OutlierDiagnosis, ValuationModel

# ── helpers ───────────────────────────────────────────────────────────────────


def _mk_diagnosis() -> OutlierDiagnosis:
    return OutlierDiagnosis(
        outlier_model=ValuationModel.DCF,
        likely_cause="永续增长率偏高",
        confidence="high",
        recommended_action="trust_consensus",
        narrative="DCF 给出 5000 偏离 PE 1500,主因永续增长率假设过乐观。",
    )


# ── 单 lens skip ──────────────────────────────────────────────────────────────


def test_scorer_skip_when_consistency_none_returns_10() -> None:
    """单 lens (consistency=None) → 10.0,evidence 含 skip / single."""
    from app.agents.critic_subagents.valuation_consistency import ValuationConsistencyScorer

    scorer = ValuationConsistencyScorer(llm=MagicMock())
    score = scorer.score(
        report_markdown="# 估值\n...",
        valuation_consistency=None,
        outlier_diagnosis=None,
        request_id="req-001",
    )
    assert score.score == 10.0
    assert "skip" in score.evidence.lower() or "single" in score.evidence.lower()
    assert score.dimension == "valuation_consistency"


# ── consistent ────────────────────────────────────────────────────────────────


def test_scorer_consistent_with_mention_high_score() -> None:
    """consistent + narrative 提及一致性 → 9.0"""
    from app.agents.critic_subagents.valuation_consistency import ValuationConsistencyScorer

    scorer = ValuationConsistencyScorer(llm=MagicMock())
    score = scorer.score(
        report_markdown="# 估值\nPE 与 DCF 估值一致,均落于 1500-1800 元区间。",
        valuation_consistency="consistent",
        outlier_diagnosis=None,
        request_id="req",
    )
    assert score.score == 9.0


def test_scorer_consistent_without_mention_mid_score() -> None:
    """consistent + narrative 未提一致性 → 8.0(still passes,但提示作者补一句)"""
    from app.agents.critic_subagents.valuation_consistency import ValuationConsistencyScorer

    scorer = ValuationConsistencyScorer(llm=MagicMock())
    score = scorer.score(
        report_markdown="# 估值\n茅台 PE 30x.",
        valuation_consistency="consistent",
        outlier_diagnosis=None,
        request_id="req",
    )
    assert score.score == 8.0


# ── moderate ──────────────────────────────────────────────────────────────────


def test_scorer_moderate_with_explanation_high_score() -> None:
    """moderate + narrative 含 偏离/差异 词 → 8.0"""
    from app.agents.critic_subagents.valuation_consistency import ValuationConsistencyScorer

    scorer = ValuationConsistencyScorer(llm=MagicMock())
    score = scorer.score(
        report_markdown="# 估值\nPE 与 DCF 存在 20% 差异,主因周期位置。",
        valuation_consistency="moderate",
        outlier_diagnosis=None,
        request_id="req",
    )
    assert score.score == 8.0


def test_scorer_moderate_without_explanation_low_score() -> None:
    """moderate + narrative 未提偏离 → 4.0(< 7.0 触发 retry)"""
    from app.agents.critic_subagents.valuation_consistency import ValuationConsistencyScorer

    scorer = ValuationConsistencyScorer(llm=MagicMock())
    score = scorer.score(
        report_markdown="# 估值\n茅台估值合理,推荐持有。",
        valuation_consistency="moderate",
        outlier_diagnosis=None,
        request_id="req",
    )
    assert score.score < 7.0
    assert score.score == 4.0


# ── severe ────────────────────────────────────────────────────────────────────


def test_scorer_severe_diagnosis_referenced_high_score() -> None:
    """severe + diagnosis.narrative 出现在 report_markdown → 9.0"""
    from app.agents.critic_subagents.valuation_consistency import ValuationConsistencyScorer

    diagnosis = _mk_diagnosis()
    scorer = ValuationConsistencyScorer(llm=MagicMock())
    score = scorer.score(
        report_markdown=(
            "# 估值\n茅台 4 lens cross-check:PE 1500, DCF 5000。"
            "DCF 给出 5000 偏离 PE 1500,主因永续增长率假设过乐观。"
        ),
        valuation_consistency="severe",
        outlier_diagnosis=diagnosis,
        request_id="req",
    )
    assert score.score == 9.0


def test_scorer_severe_diagnosis_not_referenced_low_score() -> None:
    """severe + diagnosis 存在 + narrative 未引用 → 3.0(掩盖打架信号)"""
    from app.agents.critic_subagents.valuation_consistency import ValuationConsistencyScorer

    diagnosis = _mk_diagnosis()
    scorer = ValuationConsistencyScorer(llm=MagicMock())
    score = scorer.score(
        report_markdown="# 估值\n茅台估值 1500-1800 元区间。",  # 未提 diagnosis
        valuation_consistency="severe",
        outlier_diagnosis=diagnosis,
        request_id="req",
    )
    assert score.score == 3.0


def test_scorer_severe_no_diagnosis_with_flag_mid_score() -> None:
    """severe + diagnosis None (LLM 失败) + narrative flag 不确定 → 7.0"""
    from app.agents.critic_subagents.valuation_consistency import ValuationConsistencyScorer

    scorer = ValuationConsistencyScorer(llm=MagicMock())
    score = scorer.score(
        report_markdown="# 估值\n多模型严重不一致,目前无法诊断哪个 lens 偏离。建议人工 review。",
        valuation_consistency="severe",
        outlier_diagnosis=None,
        request_id="req",
    )
    assert score.score == 7.0


def test_scorer_severe_no_diagnosis_no_flag_low_score() -> None:
    """severe + diagnosis None + narrative 也没 flag → 4.0"""
    from app.agents.critic_subagents.valuation_consistency import ValuationConsistencyScorer

    scorer = ValuationConsistencyScorer(llm=MagicMock())
    score = scorer.score(
        report_markdown="# 估值\n茅台估值 1500-1800 元区间。",
        valuation_consistency="severe",
        outlier_diagnosis=None,
        request_id="req",
    )
    assert score.score == 4.0


# ── shape ─────────────────────────────────────────────────────────────────────


def test_scorer_returns_critic_dimension_score_with_correct_fields() -> None:
    """所有 case 返 CriticDimensionScore,带 dimension / score / evidence / request_id."""
    from app.agents.critic_subagents.valuation_consistency import ValuationConsistencyScorer
    from app.agents.schemas import CriticDimensionScore

    scorer = ValuationConsistencyScorer(llm=MagicMock())
    score = scorer.score(
        report_markdown="一致",
        valuation_consistency="consistent",
        outlier_diagnosis=None,
        request_id="req-42",
    )
    assert isinstance(score, CriticDimensionScore)
    assert score.dimension == "valuation_consistency"
    assert 0.0 <= score.score <= 10.0
    assert score.evidence  # non-empty
    assert score.sub_agent_request_id == "req-42"
