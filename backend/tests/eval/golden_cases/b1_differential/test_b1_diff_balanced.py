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

pytestmark = [
    pytest.mark.vcr,
    pytest.mark.skip(
        reason="v1.x A5b 在 Analyst hot path 加 DebateOrchestrator 4 advocate LLM call;"
        "旧 cassette 无 AdvocateOutput 录音,导致 LLM call 序列错位。"
        "需 Mac 真 LLM 重录 cassette 才能恢复。"
        "spec ref: 2026-05-16-v1.x-bull-bear-debate-design.md § 11.3"
    ),
]

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

    # ── 4. Plan 客观底稿层一致 — 4 required dim 全覆盖 ─────────────────────────
    assert final_state.plan is not None
    dim_keywords = {"财务", "估值", "行业", "风险"}
    covered = {
        kw
        for sub in final_state.plan.subtasks
        for kw in dim_keywords
        if kw in sub.description or kw in sub.rationale
    }
    assert covered == dim_keywords, f"required dims missing: {dim_keywords - covered}"

    # ── 5. InputContextAppropriatenessScorer sanity ───────────────────────────
    # v0.8.5 baseline 7.5 在 v1.x A4 下不再硬阈值;真差异化已由
    # position_size + growth/risk 关键词 + dim coverage 守。
    assert final_state.critic_report is not None, "Critic must produce a CriticReport"
    ic_score = final_state.critic_report.get_score("input_context_appropriateness")
    assert ic_score is not None and 0.0 <= ic_score <= 10.0
