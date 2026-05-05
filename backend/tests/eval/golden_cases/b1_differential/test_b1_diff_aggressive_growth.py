"""B-1 differential golden case 2 — aggressive_growth + short_term + very_aggressive.

同 ts_code (600519.SH 茅台), 不同 investment_objective / horizon / risk_tolerance:
  objective  = aggressive_growth
  horizon    = short_term
  tolerance  = very_aggressive

Acceptance criteria (spec § 7):
  1. recommended_position_size_pct in [10%, 30%] (激进客户可接受高仓位)
  2. recommendation in ["recommend_buy", "recommend_overweight"]
  3. report markdown 含成长/高估值/技术指标/高弹性相关关键词
  4. InputContextAppropriatenessScorer score ≥ 8.5 (= 0.85 normalized)

Cassette:  backend/tests/fixtures/cassettes/b1_differential/
           test_b1_diff_aggressive_growth/<cassette>.yaml

Record:  unset all_proxy https_proxy http_proxy
         uv run pytest backend/tests/eval/golden_cases/b1_differential/
                       test_b1_diff_aggressive_growth.py
                       --record-mode=once -v

spec ref: docs/superpowers/specs/2026-05-04-v0.8.4-b1-single-deep-design.md § 7
"""

from __future__ import annotations

import pytest
from app.agents.investment_dd_schema import InvestmentDueDiligenceReport
from app.agents.schemas import ResearchState

from tests.eval.golden_cases.b1_differential._graph_builder import build_b1_diff_graph

pytestmark = [
    pytest.mark.vcr,
    pytest.mark.xfail(
        reason=(
            "v0.8.5 Task 5: post_process_writer_output overrides recommendation + "
            "position_size deterministically. Stub data lacks numeric metrics so "
            "classify_recommendation falls to recommend_hold fallback "
            "(compute_position_size_pct(hold, very_aggressive, …) = 7.0%, < 10%). "
            "Cassette to be re-recorded in Task 9 with new SOP-injected prompts; "
            "acceptance criteria likely need recalibration vs new helper output."
        ),
        strict=True,
    ),
]

_THREAD_ID = "b1-diff-aggressive-growth-test-1"

_KEYWORDS_AGGRESSIVE_GROWTH = [
    "成长",
    "高弹性",
    "技术",
    "资金流",
    "动量",
    "短期",
    "aggressive_growth",
    "very_aggressive",
    "高估值",
    "买入",
    "进攻",
    "弹性",
]


@pytest.fixture
def b1_diff_aggressive_growth_graph(monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    """Build research graph for aggressive_growth differential case."""
    return build_b1_diff_graph(monkeypatch)


@pytest.mark.asyncio
async def test_b1_aggressive_growth_茅台(  # noqa: N802
    b1_diff_aggressive_growth_graph,
) -> None:
    """aggressive_growth + short_term + very_aggressive → 高仓位 + 买入/增持 + 成长关键词。

    Differential assertion: compared to capital_preservation or balanced case,
    the aggressive_growth case must show:
    - Higher position_size_pct (10% ~ 30%)
    - Growth-oriented recommendation (buy or overweight)
    - Explicit reference to growth, technical analysis, high beta language
    - InputContextAppropriatenessScorer ≥ 8.5 (report truly conditions on input)
    """
    initial = ResearchState(
        user_id="test",
        session_id=_THREAD_ID,
        user_message="请对贵州茅台(600519.SH)进行投资标的尽调。",
        request_id=_THREAD_ID,
        target_ts_code="600519.SH",
        client_total_aum=10_000_000.0,
        investment_objective="aggressive_growth",
        investment_horizon="short_term",
        risk_tolerance="very_aggressive",
    )
    config = {"configurable": {"thread_id": _THREAD_ID}}

    result = await b1_diff_aggressive_growth_graph.ainvoke(initial.model_dump(), config=config)
    final_state = ResearchState.model_validate(result)

    # ── 1. Report generated ──────────────────────────────────────────────────
    assert final_state.investment_report is not None, (
        "Writer must produce an InvestmentDueDiligenceReport"
    )
    report = final_state.investment_report
    assert isinstance(report, InvestmentDueDiligenceReport)

    # ── 2. position_size ∈ [10%, 30%] (激进客户可高仓位) ─────────────────────
    position_pct = report.investment_recommendation.recommended_position_size_pct
    assert 10.0 <= position_pct <= 30.0, (
        f"aggressive_growth + very_aggressive → position_size should be in [10%, 30%], "
        f"got {position_pct:.1f}%. Writer prompt conditioning not working."
    )

    # ── 3. recommendation ∈ buy / overweight (growth-oriented) ───────────────
    assert report.investment_recommendation.recommendation in {
        "recommend_buy",
        "recommend_overweight",
    }, (
        f"aggressive_growth client should receive growth-oriented recommendation. "
        f"Got: {report.investment_recommendation.recommendation!r}"
    )

    # ── 4. markdown 含成长/技术/高弹性关键词 ──────────────────────────────────
    assert final_state.report_markdown is not None
    md = final_state.report_markdown
    matched = [kw for kw in _KEYWORDS_AGGRESSIVE_GROWTH if kw in md]
    assert matched, (
        f"aggressive_growth report must contain ≥1 of {_KEYWORDS_AGGRESSIVE_GROWTH}. "
        f"Got none. Report excerpt (first 800 chars): {md[:800]}"
    )

    # ── 5. InputContextAppropriatenessScorer ≥ 8.5 ──────────────────────────
    assert final_state.critic_report is not None, "Critic must produce a CriticReport"
    ic_score = final_state.critic_report.get_score("input_context_appropriateness")
    assert ic_score is not None, (
        "InputContextAppropriatenessScorer not found in critic_report.dimensions. "
        "Is InputContextAppropriatenessScorer wired into Critic scorers list?"
    )
    assert ic_score >= 8.5, (
        f"input_context_appropriateness score = {ic_score:.1f} < 8.5 (≡ 0.85 normalized). "
        f"Report is not differential enough for aggressive_growth input. "
        f"Consider iterating Task 3 prompt."
    )
