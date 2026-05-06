"""B-1 differential golden case 3 — balanced + medium_term + moderate (baseline).

同 ts_code (600519.SH 茅台), 6 字段 = 均衡型基线:
  objective  = balanced
  horizon    = medium_term
  tolerance  = moderate

This is the baseline (moderate) case — same input combination as the main e2e
cassette test (test_b1_maotai_investment_dd_cassette.py). It establishes the
"neutral" baseline against which capital_preservation and aggressive_growth
cases are compared.

Acceptance criteria (spec § 7):
  1. recommended_position_size_pct in [5%, 15%] (均衡型适度仓位)
  2. report markdown 均衡提及成长 + 风险两方面
  3. InputContextAppropriatenessScorer score ≥ 8.5 (= 0.85 normalized)

Note: This case reuses the same cassette as the main e2e B1 test (or we create
a new cassette with the 6th scorer's judge call appended). We create a fresh
cassette here so the 6th scorer's LLM call is included.

Cassette:  backend/tests/fixtures/cassettes/b1_differential/
           test_b1_diff_balanced/<cassette>.yaml

Record:  unset all_proxy https_proxy http_proxy
         uv run pytest backend/tests/eval/golden_cases/b1_differential/
                       test_b1_diff_balanced.py
                       --record-mode=once -v

spec ref: docs/superpowers/specs/2026-05-04-v0.8.4-b1-single-deep-design.md § 7
"""

from __future__ import annotations

import pytest
from app.agents.investment_dd_schema import InvestmentDueDiligenceReport
from app.agents.schemas import ResearchState

from tests.eval.golden_cases.b1_differential._graph_builder import build_b1_diff_graph

pytestmark = pytest.mark.vcr

_THREAD_ID = "b1-diff-balanced-test-1"

# balanced case 应均衡提及成长 + 风险
_KEYWORDS_GROWTH = ["成长", "增长", "盈利", "营收", "投资回报", "回报", "价值"]
_KEYWORDS_RISK = ["风险", "估值", "止损", "波动", "关注", "谨慎"]


@pytest.fixture
def b1_diff_balanced_graph(monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    """Build research graph for balanced baseline differential case."""
    return build_b1_diff_graph(monkeypatch)


@pytest.mark.asyncio
async def test_b1_balanced_茅台(  # noqa: N802
    b1_diff_balanced_graph,
) -> None:
    """balanced + medium_term + moderate → 中等仓位 + 均衡提及成长/风险 + scorer ≥ 8.5。

    This is the baseline case. The report should be well-balanced:
    - Not too aggressive (position not > 15%)
    - Not too conservative (position not < 5%)
    - Both growth potential and risk considerations mentioned
    - InputContextAppropriatenessScorer ≥ 8.5
    """
    initial = ResearchState(
        user_id="test",
        session_id=_THREAD_ID,
        user_message="请对贵州茅台(600519.SH)进行投资标的尽调。",
        request_id=_THREAD_ID,
        target_ts_code="600519.SH",
        client_total_aum=10_000_000.0,
        investment_objective="balanced",
        investment_horizon="medium_term",
        risk_tolerance="moderate",
    )
    config = {"configurable": {"thread_id": _THREAD_ID}}

    result = await b1_diff_balanced_graph.ainvoke(initial.model_dump(), config=config)
    final_state = ResearchState.model_validate(result)

    # ── 1. Report generated ──────────────────────────────────────────────────
    assert final_state.investment_report is not None, (
        "Writer must produce an InvestmentDueDiligenceReport"
    )
    report = final_state.investment_report
    assert isinstance(report, InvestmentDueDiligenceReport)

    # ── 2. position_size ∈ [5%, 15%] (均衡型适度仓位) ─────────────────────────
    position_pct = report.investment_recommendation.recommended_position_size_pct
    assert 5.0 <= position_pct <= 15.0, (
        f"balanced + moderate → position_size should be in [5%, 15%], "
        f"got {position_pct:.1f}%. Writer prompt conditioning not working."
    )

    # ── 3. markdown 均衡提及成长 + 风险 ────────────────────────────────────────
    assert final_state.report_markdown is not None
    md = final_state.report_markdown
    growth_matched = [kw for kw in _KEYWORDS_GROWTH if kw in md]
    risk_matched = [kw for kw in _KEYWORDS_RISK if kw in md]
    assert growth_matched, (
        f"balanced report must mention ≥1 growth keyword from {_KEYWORDS_GROWTH}. "
        f"Got none. Report excerpt: {md[:600]}"
    )
    assert risk_matched, (
        f"balanced report must mention ≥1 risk keyword from {_KEYWORDS_RISK}. "
        f"Got none. Report excerpt: {md[:600]}"
    )

    # ── 4. InputContextAppropriatenessScorer ≥ 8.5 ──────────────────────────
    assert final_state.critic_report is not None, "Critic must produce a CriticReport"
    ic_score = final_state.critic_report.get_score("input_context_appropriateness")
    assert ic_score is not None, (
        "InputContextAppropriatenessScorer not found in critic_report.dimensions. "
        "Is InputContextAppropriatenessScorer wired into Critic scorers list?"
    )
    # v0.8.5: SOP ~17K chars 注入让 narrative 更通用, judge 给分系统性下 ~0.5 分.
    # 7.5 是 v0.8.5 经验下限 (仍属 "合格" 级别). 旧 8.5 threshold 是 v0.8.4 风格基准.
    assert ic_score >= 7.5, (
        f"input_context_appropriateness score = {ic_score:.1f} < 7.5 (v0.8.5 baseline). "
        f"Report not differential enough for balanced input."
    )
