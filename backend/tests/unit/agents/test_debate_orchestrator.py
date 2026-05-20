"""L0 — DebateOrchestrator 2 round × 2 advocate orchestration + fallback."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.agents.debate_schemas import AdvocateOutput, DebateTrace


def _mk_output(label: str, conf: str = "high") -> AdvocateOutput:
    return AdvocateOutput(
        arguments=[f"{label} 论据 1", f"{label} 论据 2", f"{label} 论据 3"],
        strongest_argument=f"{label} 最强",
        rebut_targets=[],
        confidence=conf,  # type: ignore[arg-type]
    )


def _build_state():  # noqa: ANN202
    from app.agents.schemas import ResearchState

    return ResearchState(user_id="u", session_id="s", user_message="m", request_id="r")


def test_orchestrator_2_round_happy_path() -> None:
    """Round 1 + Round 2 全 success → DebateTrace 4 字段都填, rounds_completed=2."""
    from app.agents.debate_orchestrator import DebateOrchestrator

    bull = MagicMock()
    bull.advocate_round_1 = MagicMock(return_value=_mk_output("bull_v1"))
    bull.advocate_round_2 = MagicMock(return_value=_mk_output("bull_v2"))
    bear = MagicMock()
    bear.advocate_round_1 = MagicMock(return_value=_mk_output("bear_v1"))
    bear.advocate_round_2 = MagicMock(return_value=_mk_output("bear_v2"))

    orchestrator = DebateOrchestrator(bull=bull, bear=bear)
    trace = orchestrator.run(_build_state())

    assert trace is not None
    assert isinstance(trace, DebateTrace)
    assert trace.bull_v1 is not None and "bull_v1" in trace.bull_v1.arguments[0]
    assert trace.bear_v1 is not None and "bear_v1" in trace.bear_v1.arguments[0]
    assert trace.bull_v2 is not None and "bull_v2" in trace.bull_v2.arguments[0]
    assert trace.bear_v2 is not None and "bear_v2" in trace.bear_v2.arguments[0]
    assert trace.rounds_completed == 2


def test_orchestrator_round_1_all_fail_returns_none() -> None:
    """Round 1 全失败 → return None (Writer 走 v0.8.5 单线路径)."""
    from app.agents.debate_orchestrator import DebateOrchestrator

    bull = MagicMock()
    bull.advocate_round_1 = MagicMock(return_value=None)
    bear = MagicMock()
    bear.advocate_round_1 = MagicMock(return_value=None)

    orchestrator = DebateOrchestrator(bull=bull, bear=bear)
    trace = orchestrator.run(_build_state())
    assert trace is None


def test_orchestrator_round_2_all_fail_uses_round_1() -> None:
    """Round 1 成功 + Round 2 全失败 → 用 round 1 final, rounds_completed=1."""
    from app.agents.debate_orchestrator import DebateOrchestrator

    bull = MagicMock()
    bull.advocate_round_1 = MagicMock(return_value=_mk_output("bull_v1"))
    bull.advocate_round_2 = MagicMock(return_value=None)
    bear = MagicMock()
    bear.advocate_round_1 = MagicMock(return_value=_mk_output("bear_v1"))
    bear.advocate_round_2 = MagicMock(return_value=None)

    orchestrator = DebateOrchestrator(bull=bull, bear=bear)
    trace = orchestrator.run(_build_state())

    assert trace is not None
    assert trace.bull_v1 is not None
    assert trace.bear_v1 is not None
    assert trace.bull_v2 is None
    assert trace.bear_v2 is None
    assert trace.rounds_completed == 1


def test_orchestrator_round_2_partial_fail_falls_back_v1() -> None:
    """Round 2 bull 成功 / bear 失败 → 全退到 v1 final (rounds_completed=1)."""
    from app.agents.debate_orchestrator import DebateOrchestrator

    bull = MagicMock()
    bull.advocate_round_1 = MagicMock(return_value=_mk_output("bull_v1"))
    bull.advocate_round_2 = MagicMock(return_value=_mk_output("bull_v2"))
    bear = MagicMock()
    bear.advocate_round_1 = MagicMock(return_value=_mk_output("bear_v1"))
    bear.advocate_round_2 = MagicMock(return_value=None)  # bear v2 失败

    orchestrator = DebateOrchestrator(bull=bull, bear=bear)
    trace = orchestrator.run(_build_state())

    assert trace is not None
    assert trace.rounds_completed == 1


def test_orchestrator_returns_trace_with_cost_and_latency() -> None:
    from app.agents.debate_orchestrator import DebateOrchestrator

    bull = MagicMock()
    bull.advocate_round_1 = MagicMock(return_value=_mk_output("bull_v1"))
    bull.advocate_round_2 = MagicMock(return_value=_mk_output("bull_v2"))
    bear = MagicMock()
    bear.advocate_round_1 = MagicMock(return_value=_mk_output("bear_v1"))
    bear.advocate_round_2 = MagicMock(return_value=_mk_output("bear_v2"))

    orchestrator = DebateOrchestrator(bull=bull, bear=bear)
    trace = orchestrator.run(_build_state())
    assert trace is not None
    assert trace.total_cost_cny >= 0.0
    assert trace.total_latency_ms >= 0


def test_orchestrator_round_2_advocates_receive_round_1_opposition() -> None:
    """Round 2 调用必须传 bull_v1 / bear_v1 作 advocate_round_2 参数."""
    from app.agents.debate_orchestrator import DebateOrchestrator

    bull_v1 = _mk_output("bull_v1")
    bear_v1 = _mk_output("bear_v1")
    bull = MagicMock()
    bull.advocate_round_1 = MagicMock(return_value=bull_v1)
    bull.advocate_round_2 = MagicMock(return_value=_mk_output("bull_v2"))
    bear = MagicMock()
    bear.advocate_round_1 = MagicMock(return_value=bear_v1)
    bear.advocate_round_2 = MagicMock(return_value=_mk_output("bear_v2"))

    orchestrator = DebateOrchestrator(bull=bull, bear=bear)
    orchestrator.run(_build_state())

    # bull round 2 接收 bear_v1
    bull_round_2_call = bull.advocate_round_2.call_args
    assert bull_round_2_call.kwargs.get("bear_v1") is bear_v1 or (
        bull_round_2_call.args and bull_round_2_call.args[1] is bear_v1
    )

    # bear round 2 接收 bull_v1
    bear_round_2_call = bear.advocate_round_2.call_args
    assert bear_round_2_call.kwargs.get("bull_v1") is bull_v1 or (
        bear_round_2_call.args and bear_round_2_call.args[1] is bull_v1
    )
