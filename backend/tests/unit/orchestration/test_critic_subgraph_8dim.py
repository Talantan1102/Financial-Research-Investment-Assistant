"""Critic subgraph fan-out — v1.x A5b has 8 scorers (dialectical_balance added)."""

from __future__ import annotations

from app.orchestration.critic_subgraph import _CriticSubState, _planner_router


def test_planner_router_sends_to_8_scorers() -> None:
    state = _CriticSubState(
        user_id="u",
        session_id="s",
        user_message="m",
        request_id="r",
    )
    sends = _planner_router(state)
    assert len(sends) == 8
    names = {s.node for s in sends}
    expected = {
        "scorer_factuality",
        "scorer_coverage",
        "scorer_insight",
        "scorer_structure",
        "scorer_conciseness",
        "scorer_input_context",
        "scorer_valuation_consistency",  # v1.x A5a 第 7 维
        "scorer_dialectical_balance",  # v1.x A5b 第 8 维
    }
    assert names == expected
    assert "scorer_plan_correctness" not in names


def test_build_critic_subgraph_no_plan_correctness_node() -> None:
    """Compiled subgraph should not contain a plan_correctness scorer node."""
    from unittest.mock import MagicMock

    from app.orchestration.critic_subgraph import build_critic_subgraph

    critic = MagicMock()
    g = build_critic_subgraph(critic)
    node_names = set(g.get_graph().nodes.keys()) if hasattr(g, "get_graph") else set()
    if node_names:
        assert "scorer_plan_correctness" not in node_names
        # v1.x A5a guard — valuation_consistency node真存在
        assert "scorer_valuation_consistency" in node_names
        # v1.x A5b guard — dialectical_balance node真存在
        assert "scorer_dialectical_balance" in node_names
    else:
        assert g is not None
