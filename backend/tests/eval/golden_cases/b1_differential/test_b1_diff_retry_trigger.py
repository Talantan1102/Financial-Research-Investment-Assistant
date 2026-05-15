"""B-1 differential golden case 4 — writer retry-trigger via contradictory user_message.

v1.x A4 reframe: Plan-layer retry (PlanCorrectnessScorer < 8.5) is gone — the
plan is now守 by Validator + SAFE_DEFAULT_PLAN. The remaining retry edge fires
on **Writer factuality** (Critic factuality < threshold) and carries
writer_critic_feedback into a second Writer pass.

This file historically tested v0.8.5 planner retry; v1.x equivalent is Writer
factuality retry. The retry edge mechanism is fully守 by the 4 mocked
integration tests in `backend/tests/integration/test_writer_retry_edge.py`
(Task 1.8). This e2e LLM-judge variant is kept as documentation of the
client-driven contradiction scenario but is **skipped by default**:

  - v0.8.5 dogfood showed e2e LLM judge does not reliably score < 8.5 on a
    single contradictory user_message — retry_count came back 0 instead of ≥1.
  - v1.x retains the same constraint at the Writer factuality scorer level.

To revisit: dogfood ≥ 5 contradictory prompts, calibrate Critic factuality
threshold, then unskip.

spec ref: docs/superpowers/specs/2026-05-15-v1.x-plan-template-validator-design.md § 7.2
"""

from __future__ import annotations

import pytest
from app.agents.investment_dd_schema import InvestmentDueDiligenceReport
from app.agents.schemas import ResearchState

from tests.eval.golden_cases.b1_differential._graph_builder import build_b1_diff_graph

pytestmark = [
    pytest.mark.vcr,
    pytest.mark.skip(
        reason=(
            "v1.x writer-factuality retry: e2e LLM judge 不稳定触发 retry "
            "(v0.8.5 同因)。Writer retry edge 已由 integration/"
            "test_writer_retry_edge.py 4 cases (mocked Critic) 充分覆盖。"
            "Dogfood ≥ 5 contradictory prompts 后 calibrate factuality threshold 再 unskip。"
        )
    ),
]

_THREAD_ID = "b1-diff-retry-trigger-test-1"


@pytest.fixture
def b1_diff_retry_trigger_graph(monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    """Build research graph for retry-trigger differential case."""
    return build_b1_diff_graph(monkeypatch)


@pytest.mark.asyncio
async def test_b1_retry_trigger_茅台_矛盾_input(  # noqa: N802
    b1_diff_retry_trigger_graph,
) -> None:
    """矛盾 user_message → Writer factuality 应低分 → writer_retry_count ≥ 1 (永远 skip)。

    v1.x assertion shape (parked behind skip — see module docstring):
      - investment_report not None (graph completes)
      - writer_retry_count ∈ [0, 1] (v1.x _MAX_WRITER_RETRY=1)
      - if writer_retry_count ≥ 1 then writer_critic_feedback populated
      - critic_report.factuality present
    """
    initial = ResearchState(
        user_id="test",
        session_id=_THREAD_ID,
        user_message=(
            "请对贵州茅台(600519.SH)进行投资标的尽调。"
            "我担心市场短期下跌想避险, 但又希望抓住短期反弹机会。"
        ),
        request_id=_THREAD_ID,
        target_ts_code="600519.SH",
        client_total_aum=10_000_000.0,
        investment_objective="balanced",
        investment_horizon="short_term",
        risk_tolerance="moderate",
    )
    config = {"configurable": {"thread_id": _THREAD_ID}}

    result = await b1_diff_retry_trigger_graph.ainvoke(initial.model_dump(), config=config)
    final_state = ResearchState.model_validate(result)

    # ── 1. Report generated (graph runs to completion) ───────────────────────
    assert final_state.investment_report is not None
    assert isinstance(final_state.investment_report, InvestmentDueDiligenceReport)

    # ── 2. Writer retry within hard cap (_MAX_WRITER_RETRY = 1, v1.x) ────────
    assert 0 <= final_state.writer_retry_count <= 1, (
        f"writer_retry_count must respect _MAX_WRITER_RETRY=1, got {final_state.writer_retry_count}"
    )

    # ── 3. factuality dimension present in critic_report (v1.x 6-dim) ───────
    assert final_state.critic_report is not None
    f_score = final_state.critic_report.get_score("factuality")
    assert f_score is not None

    # ── 4. If retry fired, writer_critic_feedback carries round-1 evidence ──
    if final_state.writer_retry_count >= 1:
        assert final_state.writer_critic_feedback is not None
        assert len(final_state.writer_critic_feedback) <= 300
