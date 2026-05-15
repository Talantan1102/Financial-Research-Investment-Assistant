"""B-1 differential golden case 1 — capital_preservation + long_term + conservative.

同 ts_code (600519.SH 茅台), 不同 investment_objective / horizon / risk_tolerance:
  objective  = capital_preservation
  horizon    = long_term
  tolerance  = conservative

Acceptance criteria (spec § 7):
  1. recommended_position_size_pct ≤ 10% (保本型客户不高仓位)
  2. recommendation in ["recommend_hold", "recommend_overweight"] (不强烈买/卖)
  3. report markdown 含保本/稳健/防御类关键词
  4. InputContextAppropriatenessScorer score ≥ 8.5 (= 0.85 normalized)

Cassette:  backend/tests/fixtures/cassettes/b1_differential/
           test_b1_diff_capital_preservation/<cassette>.yaml

Record:  unset all_proxy https_proxy http_proxy
         uv run pytest backend/tests/eval/golden_cases/b1_differential/
                       test_b1_diff_capital_preservation.py
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
    pytest.mark.skip(
        reason="v1.x cassette pending re-record on Mac (Task 1.11/1.12). "
        "Re-record with VCR_RECORD_MODE=new_episodes after setting "
        "DASHSCOPE_API_KEY / TUSHARE_API_TOKEN / BOCHA_API_KEY in backend/.env."
    ),
]

_THREAD_ID = "b1-diff-capital-preservation-test-1"

_KEYWORDS_CAPITAL_PRESERVATION = [
    "保本",
    "稳健",
    "防御",
    "低波动",
    "保守",
    "capital_preservation",
    "conservative",
    "下行保护",
    "安全边际",
]


@pytest.fixture
def b1_diff_capital_preservation_graph(monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    """Build research graph for capital_preservation differential case."""
    return build_b1_diff_graph(monkeypatch)


@pytest.mark.asyncio
async def test_b1_capital_preservation_茅台(  # noqa: N802
    b1_diff_capital_preservation_graph,
) -> None:
    """capital_preservation + long_term + conservative → 低仓位 + 持有/增持 + 保本关键词。

    Differential assertion: compared to balanced or aggressive_growth case,
    the capital_preservation case must show:
    - Lower position_size_pct (≤ 10%)
    - Risk-averse recommendation (hold or overweight, never strong buy)
    - Explicit reference to capital preservation language
    - InputContextAppropriatenessScorer ≥ 8.5 (report truly conditions on input)
    """
    initial = ResearchState(
        user_id="test",
        session_id=_THREAD_ID,
        user_message="请对贵州茅台(600519.SH)进行投资标的尽调。",
        request_id=_THREAD_ID,
        target_ts_code="600519.SH",
        client_total_aum=10_000_000.0,
        investment_objective="capital_preservation",
        investment_horizon="long_term",
        risk_tolerance="conservative",
    )
    config = {"configurable": {"thread_id": _THREAD_ID}}

    result = await b1_diff_capital_preservation_graph.ainvoke(initial.model_dump(), config=config)
    final_state = ResearchState.model_validate(result)

    # ── 1. Report generated ──────────────────────────────────────────────────
    assert final_state.investment_report is not None, (
        "Writer must produce an InvestmentDueDiligenceReport"
    )
    report = final_state.investment_report
    assert isinstance(report, InvestmentDueDiligenceReport)

    # ── 2. position_size ≤ 10% (保本型 conservative) ─────────────────────────
    position_pct = report.investment_recommendation.recommended_position_size_pct
    assert position_pct <= 10.0, (
        f"capital_preservation + conservative → position_size must be ≤ 10%, "
        f"got {position_pct:.1f}%. Writer prompt conditioning not working."
    )

    # ── 3. recommendation != strong buy (capital_preservation ≠ aggressive) ─────
    recommendation = report.investment_recommendation.recommendation
    assert recommendation != "recommend_buy", (
        f"capital_preservation client should not get strong buy, got {recommendation}"
    )

    # ── 4. markdown 含保本/稳健/防御关键词 ──────────────────────────────────────
    assert final_state.report_markdown is not None
    md = final_state.report_markdown
    matched = [kw for kw in _KEYWORDS_CAPITAL_PRESERVATION if kw in md]
    assert matched, (
        f"capital_preservation report must contain ≥1 of {_KEYWORDS_CAPITAL_PRESERVATION}. "
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
        f"Report is not differential enough for capital_preservation input. "
        f"Consider iterating Task 3 prompt."
    )
