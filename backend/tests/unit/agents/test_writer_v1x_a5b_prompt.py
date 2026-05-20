"""L0 — Writer prompt v1.x A5b bull/bear debate cross-check block."""

from __future__ import annotations

from app.agents.debate_schemas import AdvocateOutput, DebateTrace
from app.agents.schemas import ResearchState


def _mk_state(debate_trace: DebateTrace | None = None) -> ResearchState:
    return ResearchState(
        user_id="u",
        session_id="s",
        user_message="尽调茅台",
        request_id="r",
        target_ts_code="600519.SH",
        client_total_aum=50_000_000_000.0,
        investment_objective="balanced",
        investment_horizon="medium_term",
        risk_tolerance="moderate",
        debate_trace=debate_trace,
    )


def _mk_advocate(label: str, strongest: str) -> AdvocateOutput:
    return AdvocateOutput(
        arguments=[f"{label}_1", f"{label}_2", f"{label}_3"],
        strongest_argument=strongest,
        confidence="high",
    )


def test_prompt_no_debate_trace_omits_block() -> None:
    """debate_trace=None → prompt 不含 v1.x A5b debate block."""
    from app.agents.writer import build_investment_dd_prompt

    prompt = build_investment_dd_prompt(_mk_state(None))
    assert "v1.x A5b debate" not in prompt
    assert "bull_case" not in prompt


def test_prompt_rounds_completed_2_includes_v2() -> None:
    """rounds=2 → prompt 含 bull_v2 + bear_v2 + strongest 引用要求."""
    from app.agents.writer import build_investment_dd_prompt

    trace = DebateTrace(
        bull_v1=_mk_advocate("bull_v1", "v1 strongest bull"),
        bear_v1=_mk_advocate("bear_v1", "v1 strongest bear"),
        bull_v2=_mk_advocate("bull_v2", "v2 strongest bull"),
        bear_v2=_mk_advocate("bear_v2", "v2 strongest bear"),
        total_cost_cny=0.003,
        total_latency_ms=500,
        rounds_completed=2,
    )
    prompt = build_investment_dd_prompt(_mk_state(trace))
    assert "v1.x A5b debate" in prompt
    assert "bull_v2_1" in prompt
    assert "bear_v2_1" in prompt
    assert "v2 strongest bull" in prompt
    assert "v2 strongest bear" in prompt


def test_prompt_rounds_completed_1_uses_v1() -> None:
    """rounds=1 → prompt 用 v1 (fallback path)."""
    from app.agents.writer import build_investment_dd_prompt

    trace = DebateTrace(
        bull_v1=_mk_advocate("bull_v1", "v1 strongest bull"),
        bear_v1=_mk_advocate("bear_v1", "v1 strongest bear"),
        bull_v2=None,
        bear_v2=None,
        total_cost_cny=0.001,
        total_latency_ms=200,
        rounds_completed=1,
    )
    prompt = build_investment_dd_prompt(_mk_state(trace))
    assert "v1.x A5b debate" in prompt
    assert "bull_v1_1" in prompt
    assert "bear_v1_1" in prompt
    assert "v1 strongest bull" in prompt


def test_prompt_includes_narrative_requirement() -> None:
    """prompt 必须明示 narrative 必须 ≥2 bull mention + ≥2 bear mention."""
    from app.agents.writer import build_investment_dd_prompt

    trace = DebateTrace(
        bull_v1=_mk_advocate("bull_v1", "x"),
        bear_v1=_mk_advocate("bear_v1", "y"),
        bull_v2=_mk_advocate("bull_v2", "z"),
        bear_v2=_mk_advocate("bear_v2", "w"),
        total_cost_cny=0.003,
        total_latency_ms=500,
        rounds_completed=2,
    )
    prompt = build_investment_dd_prompt(_mk_state(trace))
    assert "≥ 2" in prompt or ">= 2" in prompt or "至少 2" in prompt or "双向" in prompt
