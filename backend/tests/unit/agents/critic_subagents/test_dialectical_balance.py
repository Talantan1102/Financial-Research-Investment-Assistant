"""L0 — Critic 第 8 维 DialecticalBalanceScorer rule-based."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.agents.debate_schemas import AdvocateOutput, DebateTrace
from app.agents.schemas import CriticDimensionScore, ResearchState


def _mk_advocate(args: list[str]) -> AdvocateOutput:
    return AdvocateOutput(
        arguments=args,
        strongest_argument=args[0],
        confidence="high",
    )


def _mk_trace_with_args(bull_args: list[str], bear_args: list[str]) -> DebateTrace:
    return DebateTrace(
        bull_v1=_mk_advocate(bull_args),
        bear_v1=_mk_advocate(bear_args),
        bull_v2=_mk_advocate(bull_args),
        bear_v2=_mk_advocate(bear_args),
        total_cost_cny=0.0,
        total_latency_ms=0,
        rounds_completed=2,
    )


def test_scorer_skip_when_debate_trace_none() -> None:
    """state.debate_trace=None → 10.0 skip."""
    from app.agents.critic_subagents.dialectical_balance import DialecticalBalanceScorer

    scorer = DialecticalBalanceScorer(llm=MagicMock())
    state = ResearchState(
        user_id="u",
        session_id="s",
        user_message="m",
        request_id="r",
        report_markdown="any",
        debate_trace=None,
    )
    result = scorer.step(state)
    score: CriticDimensionScore = result.state_update["dialectical_balance_score"]
    assert score.score == 10.0
    assert "skip" in score.evidence.lower() or "no debate" in score.evidence.lower()


def test_scorer_both_sides_2plus_mention_high_score() -> None:
    """narrative 双向 ≥2 each → 9.0."""
    from app.agents.critic_subagents.dialectical_balance import DialecticalBalanceScorer

    trace = _mk_trace_with_args(
        bull_args=["品牌护城河 30 年", "ROE 30% 稳定", "提价权强"],
        bear_args=["PE 接近历史高位", "反腐影响", "年轻人不喝白酒"],
    )
    md = (
        "# § 6\n"
        "看多论据: 品牌护城河 30 年 + ROE 30% 稳定。\n"
        "看空论据: PE 接近历史高位 + 反腐影响。\n"
        "综合推荐: 持有。"
    )
    scorer = DialecticalBalanceScorer(llm=MagicMock())
    state = ResearchState(
        user_id="u",
        session_id="s",
        user_message="m",
        request_id="r",
        report_markdown=md,
        debate_trace=trace,
    )
    result = scorer.step(state)
    score = result.state_update["dialectical_balance_score"]
    assert score.score == 9.0


def test_scorer_one_sided_mention_low_score() -> None:
    """narrative 只提一边 ≥2 → 3.0 (掩盖一面)."""
    from app.agents.critic_subagents.dialectical_balance import DialecticalBalanceScorer

    trace = _mk_trace_with_args(
        bull_args=["品牌护城河 30 年", "ROE 30% 稳定", "提价权强"],
        bear_args=["PE 接近历史高位", "反腐影响", "年轻人不喝白酒"],
    )
    md = "# § 6\n看多论据: 品牌护城河 30 年 + ROE 30% 稳定 + 提价权强。\n推荐: 买入。"
    scorer = DialecticalBalanceScorer(llm=MagicMock())
    state = ResearchState(
        user_id="u",
        session_id="s",
        user_message="m",
        request_id="r",
        report_markdown=md,
        debate_trace=trace,
    )
    result = scorer.step(state)
    score = result.state_update["dialectical_balance_score"]
    assert score.score == 3.0


def test_scorer_both_sides_one_each_mid_score() -> None:
    """narrative 双方都只提 1 条 → 6.0 (论据稀薄)."""
    from app.agents.critic_subagents.dialectical_balance import DialecticalBalanceScorer

    trace = _mk_trace_with_args(
        bull_args=["品牌护城河 30 年", "ROE 30% 稳定", "提价权强"],
        bear_args=["PE 接近历史高位", "反腐影响", "年轻人不喝白酒"],
    )
    md = "# § 6\n看多: 品牌护城河 30 年。 看空: PE 接近历史高位。 推荐: 持有。"
    scorer = DialecticalBalanceScorer(llm=MagicMock())
    state = ResearchState(
        user_id="u",
        session_id="s",
        user_message="m",
        request_id="r",
        report_markdown=md,
        debate_trace=trace,
    )
    result = scorer.step(state)
    score = result.state_update["dialectical_balance_score"]
    assert score.score == 6.0


def test_scorer_empty_arguments_returns_skip() -> None:
    """bull_v1/v2 + bear_v1/v2 全 None → 10.0 skip."""
    from app.agents.critic_subagents.dialectical_balance import DialecticalBalanceScorer

    trace = DebateTrace(
        bull_v1=None,
        bear_v1=None,
        bull_v2=None,
        bear_v2=None,
        total_cost_cny=0.0,
        total_latency_ms=0,
        rounds_completed=0,
    )
    scorer = DialecticalBalanceScorer(llm=MagicMock())
    state = ResearchState(
        user_id="u",
        session_id="s",
        user_message="m",
        request_id="r",
        report_markdown="x",
        debate_trace=trace,
    )
    result = scorer.step(state)
    score = result.state_update["dialectical_balance_score"]
    assert score.score == 10.0
