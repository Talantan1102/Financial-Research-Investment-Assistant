"""B-1 differential golden case 2 — aggressive_growth + short_term + very_aggressive.

同 ts_code (600519.SH 茅台), 不同 investment_objective / horizon / risk_tolerance:
  objective  = aggressive_growth
  horizon    = short_term
  tolerance  = very_aggressive

Acceptance criteria (去推荐改造后):
  1. § 6 为综合研判(investment_synthesis,无评级/仓位/目标价字段)
  2. report markdown 含成长/高估值/技术指标/高弹性关键词(研究重心偏成长)
  3. 4 个 required dim(财务/估值/行业/风险)全覆盖(客观底稿层一致)
  4. InputContextAppropriatenessScorer 已接线(分数在 [0,10])

Cassette:  backend/tests/fixtures/cassettes/b1_differential/
           test_b1_diff_aggressive_growth/<cassette>.yaml

Record (需有效 DASHSCOPE_API_KEY): unset http_proxy https_proxy all_proxy;
         VCR_RECORD_MODE=once python -m pytest
         backend/tests/eval/golden_cases/b1_differential/test_b1_diff_aggressive_growth.py -v

spec ref: docs/superpowers/specs/2026-05-04-v0.8.4-b1-single-deep-design.md § 7
"""

from __future__ import annotations

import pytest
from app.agents.investment_dd_schema import InvestmentDueDiligenceReport
from app.agents.schemas import ResearchState

from tests.eval.golden_cases.b1_differential._graph_builder import build_b1_diff_graph

pytestmark = [
    pytest.mark.vcr,
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
    """aggressive_growth + short_term + very_aggressive → 研究重心偏成长 + 成长关键词。

    去推荐改造后差异化(对比 capital_preservation / balanced):
    - § 6 综合研判呈现(已无评级/仓位/目标价)
    - 研究重心偏成长:markdown 含成长 / 技术 / 高弹性等关键词
    - 4 required dim 全覆盖;InputContextAppropriatenessScorer 已接线
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

    # ── 2. 去推荐:§ 6 = 综合研判(评级/仓位/目标价字段已从 schema 移除)──────────
    #    差异化不再靠仓位/评级数字,改由「研究重心」体现(见下方关键词 + InputContext)。
    syn = report.investment_synthesis
    assert syn.narrative, "§ 6 综合研判 narrative 必须非空"

    # ── 4. markdown 含成长/技术/高弹性关键词 ──────────────────────────────────
    assert final_state.report_markdown is not None
    md = final_state.report_markdown
    matched = [kw for kw in _KEYWORDS_AGGRESSIVE_GROWTH if kw in md]
    assert matched, (
        f"aggressive_growth report must contain ≥1 of {_KEYWORDS_AGGRESSIVE_GROWTH}. "
        f"Got none. Report excerpt (first 800 chars): {md[:800]}"
    )

    # ── 5. Plan 客观底稿层一致 — 4 required dim 全覆盖 ─────────────────────────
    assert final_state.plan is not None
    dim_keywords = {"财务", "估值", "行业", "风险"}
    covered = {
        kw
        for sub in final_state.plan.subtasks
        for kw in dim_keywords
        if kw in sub.description or kw in sub.rationale
    }
    assert covered == dim_keywords, f"required dims missing: {dim_keywords - covered}"

    # ── 6. InputContextAppropriatenessScorer sanity(v1.x 不再硬阈值)──────────
    # 去推荐后真差异化由 研究重心关键词 + dim coverage 守(不再有 position_size)。
    assert final_state.critic_report is not None, "Critic must produce a CriticReport"
    ic_score = final_state.critic_report.get_score("input_context_appropriateness")
    assert ic_score is not None and 0.0 <= ic_score <= 10.0
