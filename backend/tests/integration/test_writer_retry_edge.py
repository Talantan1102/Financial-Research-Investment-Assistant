"""Integration test — writer retry edge on factuality < 7.0 (v1.x)."""

from __future__ import annotations

from app.agents.schemas import CriticDimensionScore, CriticReport, ResearchState


def _mk_state_with_factuality(score: float, writer_retry_count: int = 0) -> ResearchState:
    return ResearchState(
        user_id="u",
        session_id="s",
        user_message="m",
        request_id="r",
        writer_retry_count=writer_retry_count,
        critic_report=CriticReport(
            dimensions=[
                CriticDimensionScore(
                    dimension="factuality",
                    score=score,
                    evidence="evidence text",
                    sub_agent_request_id="x",
                )
            ],
            overall_score=score,
            summary_markdown="",
        ),
    )


def test_writer_retry_triggers_when_factuality_below_threshold() -> None:
    from app.orchestration.research_graph import _writer_retry_router

    state = _mk_state_with_factuality(6.5, writer_retry_count=0)
    assert _writer_retry_router(state) == "retry"


def test_writer_retry_continues_when_at_threshold() -> None:
    from app.orchestration.research_graph import _writer_retry_router

    state = _mk_state_with_factuality(7.0, writer_retry_count=0)
    assert _writer_retry_router(state) == "continue"


def test_writer_retry_continues_when_already_retried() -> None:
    from app.orchestration.research_graph import _writer_retry_router

    state = _mk_state_with_factuality(6.5, writer_retry_count=1)
    assert _writer_retry_router(state) == "continue"


def test_writer_retry_continues_when_factuality_high() -> None:
    from app.orchestration.research_graph import _writer_retry_router

    state = _mk_state_with_factuality(8.5, writer_retry_count=0)
    assert _writer_retry_router(state) == "continue"


def test_writer_retry_continues_when_no_critic_report() -> None:
    from app.orchestration.research_graph import _writer_retry_router

    state = ResearchState(
        user_id="u",
        session_id="s",
        user_message="m",
        request_id="r",
        critic_report=None,
    )
    assert _writer_retry_router(state) == "continue"


def test_writer_retry_continues_when_factuality_score_missing() -> None:
    """critic_report exists but has no factuality dimension."""
    from app.orchestration.research_graph import _writer_retry_router

    state = ResearchState(
        user_id="u",
        session_id="s",
        user_message="m",
        request_id="r",
        critic_report=CriticReport(
            dimensions=[
                CriticDimensionScore(
                    dimension="coverage",
                    score=5.0,
                    evidence="x",
                    sub_agent_request_id="y",
                )
            ],
            overall_score=5.0,
            summary_markdown="",
        ),
    )
    assert _writer_retry_router(state) == "continue"


def test_writer_retry_state_update_bumps_count_and_extracts_feedback() -> None:
    from app.orchestration.research_graph import _writer_retry_state_update

    state = _mk_state_with_factuality(6.5, writer_retry_count=0)
    diff = _writer_retry_state_update(state)
    assert diff["writer_retry_count"] == 1
    assert "evidence text" in diff["writer_critic_feedback"]


def test_writer_retry_state_update_caps_feedback_at_300() -> None:
    from app.orchestration.research_graph import _writer_retry_state_update

    state = ResearchState(
        user_id="u",
        session_id="s",
        user_message="m",
        request_id="r",
        writer_retry_count=0,
        critic_report=CriticReport(
            dimensions=[
                CriticDimensionScore(
                    dimension="factuality",
                    score=6.0,
                    evidence="x" * 500,
                    sub_agent_request_id="y",
                )
            ],
            overall_score=6.0,
            summary_markdown="",
        ),
    )
    diff = _writer_retry_state_update(state)
    assert len(diff["writer_critic_feedback"]) == 300


# ---------------------------------------------------------------------------
# v1.x A5a — valuation_consistency OR trigger tests
# ---------------------------------------------------------------------------


def test_writer_retry_on_valuation_consistency_low() -> None:
    """factuality OK (9.0), valuation_consistency 4.0 → retry fires (< threshold)."""
    from app.orchestration.research_graph import _writer_retry_router

    state = ResearchState(
        user_id="u",
        session_id="s",
        user_message="m",
        request_id="r",
        writer_retry_count=0,
        critic_report=CriticReport(
            dimensions=[
                CriticDimensionScore(
                    dimension="factuality",
                    score=9.0,
                    evidence="all evidence accurate",
                    sub_agent_request_id="req-f",
                ),
                CriticDimensionScore(
                    dimension="valuation_consistency",
                    score=4.0,
                    evidence="moderate (narrative 未提偏离原因)",
                    sub_agent_request_id="req-vc",
                ),
            ],
            overall_score=6.5,
            summary_markdown="...",
        ),
    )
    assert _writer_retry_router(state) == "retry"


def test_writer_no_retry_on_valuation_consistency_above_threshold() -> None:
    """valuation_consistency 9.0 → no retry from this dim."""
    from app.orchestration.research_graph import _writer_retry_router

    state = ResearchState(
        user_id="u",
        session_id="s",
        user_message="m",
        request_id="r",
        writer_retry_count=0,
        critic_report=CriticReport(
            dimensions=[
                CriticDimensionScore(
                    dimension="factuality",
                    score=9.0,
                    evidence="ok",
                    sub_agent_request_id="req-f",
                ),
                CriticDimensionScore(
                    dimension="valuation_consistency",
                    score=9.0,
                    evidence="severe + narrative 显式引用 diagnosis",
                    sub_agent_request_id="req-vc",
                ),
            ],
            overall_score=9.0,
            summary_markdown="...",
        ),
    )
    assert _writer_retry_router(state) == "continue"


def test_writer_no_retry_on_valuation_consistency_missing() -> None:
    """valuation_consistency 缺失 (单 lens / 旧 case) + factuality OK → no retry."""
    from app.orchestration.research_graph import _writer_retry_router

    state = ResearchState(
        user_id="u",
        session_id="s",
        user_message="m",
        request_id="r",
        writer_retry_count=0,
        critic_report=CriticReport(
            dimensions=[
                CriticDimensionScore(
                    dimension="factuality",
                    score=9.0,
                    evidence="ok",
                    sub_agent_request_id="req-f",
                ),
                # no valuation_consistency dim
            ],
            overall_score=9.0,
            summary_markdown="...",
        ),
    )
    assert _writer_retry_router(state) == "continue"


def test_writer_retry_state_update_captures_valuation_evidence() -> None:
    """Transition node: if retry triggered by valuation_consistency, feedback captures its evidence."""
    from app.orchestration.research_graph import _writer_retry_state_update

    state = ResearchState(
        user_id="u",
        session_id="s",
        user_message="m",
        request_id="r",
        writer_retry_count=0,
        critic_report=CriticReport(
            dimensions=[
                CriticDimensionScore(
                    dimension="factuality",
                    score=9.0,
                    evidence="ok",
                    sub_agent_request_id="req-f",
                ),
                CriticDimensionScore(
                    dimension="valuation_consistency",
                    score=3.0,
                    evidence="severe + narrative 未引用 diagnosis (掩盖打架信号)",
                    sub_agent_request_id="req-vc",
                ),
            ],
            overall_score=6.0,
            summary_markdown="...",
        ),
    )
    diff = _writer_retry_state_update(state)
    assert diff["writer_retry_count"] == 1
    feedback = diff["writer_critic_feedback"]
    assert "valuation_consistency" in feedback.lower() or "未引用 diagnosis" in feedback
    assert len(feedback) <= 300


def test_writer_no_retry_when_budget_exhausted_even_if_valuation_low() -> None:
    """writer_retry_count >= _MAX_WRITER_RETRY: no retry even if valuation_consistency is low."""
    from app.orchestration.research_graph import _writer_retry_router

    state = ResearchState(
        user_id="u",
        session_id="s",
        user_message="m",
        request_id="r",
        writer_retry_count=1,  # budget exhausted
        critic_report=CriticReport(
            dimensions=[
                CriticDimensionScore(
                    dimension="valuation_consistency",
                    score=3.0,
                    evidence="severe + narrative 未引用",
                    sub_agent_request_id="req-vc",
                ),
            ],
            overall_score=3.0,
            summary_markdown="...",
        ),
    )
    assert _writer_retry_router(state) == "continue"


def test_build_research_graph_writer_retry_edge_present() -> None:
    """Smoke — graph builder wires writer_retry_transition node."""
    from unittest.mock import MagicMock

    from app.orchestration.research_graph import build_research_graph

    graph = build_research_graph(
        planner=MagicMock(),
        collector=MagicMock(),
        analyst=MagicMock(),
        writer=MagicMock(),
        critic=MagicMock(),
    )
    nodes = graph.get_graph().nodes
    assert "writer_retry_transition" in nodes
    # Old planner_retry_transition should be gone
    assert "planner_retry_transition" not in nodes
