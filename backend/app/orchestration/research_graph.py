"""Top-level v0.5 research mode StateGraph builder."""

from __future__ import annotations

from functools import partial
from typing import Any, Literal

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from app.agents.analyst import Analyst
from app.agents.critic import Critic
from app.agents.data_collector import DataCollector
from app.agents.research_planner import ResearchPlanner
from app.agents.schemas import ResearchState
from app.agents.writer import Writer
from app.orchestration.critic_subgraph import build_critic_subgraph
from app.orchestration.research_nodes import (
    analyst_node,
    data_collector_node,
    research_planner_node,
    writer_node,
)

# ---------------------------------------------------------------------------
# v0.8.5 — Constrained-router retry edge thresholds.
#
# When PlanCorrectnessScorer scores the planner's plan_id selection below
# _PLAN_CORRECTNESS_THRESHOLD AND we have not yet exceeded _MAX_PLANNER_RETRY
# rounds, the graph routes back to research_planner_node with a critic
# feedback string injected into state.planner_critic_feedback.
#
# 8.5 / 2 are spec § 4.4 hardcoded values; do not soft-code into env vars —
# changing thresholds is an architecture-level decision (cassette re-record).
# ---------------------------------------------------------------------------

_PLAN_CORRECTNESS_THRESHOLD = 8.5
_MAX_PLANNER_RETRY = 2


def _retry_router(state: ResearchState) -> Literal["retry", "continue"]:
    """Conditional edge after critic_node — decide retry vs. END.

    Returns "retry" iff plan_correctness < threshold AND retry_count < max.
    Otherwise "continue" (which is wired to END).
    """
    if state.critic_report is None:
        return "continue"
    plan_score = state.critic_report.get_score("plan_correctness")
    if plan_score is None:
        return "continue"
    if plan_score < _PLAN_CORRECTNESS_THRESHOLD and state.planner_retry_count < _MAX_PLANNER_RETRY:
        return "retry"
    return "continue"


def _retry_state_update(state: ResearchState) -> dict[str, Any]:
    """Compute state diff for the retry transition: bump count + inject feedback."""
    feedback = ""
    if state.critic_report is not None:
        for dim in state.critic_report.dimensions:
            if dim.dimension == "plan_correctness":
                feedback = dim.evidence
                break
    return {
        "planner_retry_count": state.planner_retry_count + 1,
        "planner_critic_feedback": feedback[:300],
    }


async def _planner_retry_transition_node(state: ResearchState) -> dict[str, Any]:
    """Lightweight node sandwiched between critic_node and research_planner_node.

    Single responsibility: extract plan_correctness evidence into
    planner_critic_feedback + bump planner_retry_count. Picked alternative (a)
    over (b) "planner reads its own state on entry" because the transition
    is a graph concern, not a planner concern — keeps ResearchPlanner.step()
    free of retry bookkeeping.
    """
    return _retry_state_update(state)


def build_research_graph(
    planner: ResearchPlanner,
    collector: DataCollector,
    analyst: Analyst,
    writer: Writer,
    critic: Critic,
    *,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    db_path: None = None,  # deprecated — ignored; use checkpointer= instead
) -> Any:
    """Assemble and compile the v0.5 research LangGraph StateGraph.

    Graph topology::

        START → research_planner_node → data_collector_node → analyst_node
              → writer_node → critic_node → END

    Args:
        planner:      ResearchPlanner that decomposes the user query into subtasks.
        collector:    DataCollector that executes tool calls in parallel.
        analyst:      Analyst that derives insights from tool results.
        writer:       Writer that synthesises the final research report.
        critic:       Critic subagent that scores the report on 5 dimensions.
        checkpointer: Optional pre-constructed checkpointer (sync or async).
                      Pass ``None`` for a stateless in-memory graph (tests / eval).
                      For the production async streaming path use
                      ``AsyncSqliteSaver`` (see ``make_async_chat_checkpointer``).
        db_path:      Deprecated parameter; kept for call-site compatibility.
                      Always pass ``None``.  The ``checkpointer=`` kwarg supersedes it.

    Returns:
        A compiled LangGraph object ready for .ainvoke / .astream_events.
    """
    g: StateGraph[Any, Any, Any, Any] = StateGraph(ResearchState)

    g.add_node("research_planner_node", partial(research_planner_node, planner=planner))
    g.add_node("data_collector_node", partial(data_collector_node, collector=collector))
    g.add_node("analyst_node", partial(analyst_node, analyst=analyst))
    g.add_node("writer_node", partial(writer_node, writer=writer))

    critic_subapp = build_critic_subgraph(critic)
    g.add_node("critic_node", critic_subapp)
    # v0.8.5 — retry transition node updates state.planner_retry_count +
    # planner_critic_feedback before looping back to research_planner_node.
    g.add_node("planner_retry_transition", _planner_retry_transition_node)

    g.add_edge(START, "research_planner_node")
    g.add_edge("research_planner_node", "data_collector_node")
    g.add_edge("data_collector_node", "analyst_node")
    g.add_edge("analyst_node", "writer_node")
    g.add_edge("writer_node", "critic_node")
    # v0.8.5 retry edge: critic_node → (retry → planner_retry_transition →
    # research_planner_node) | (continue → END)
    g.add_conditional_edges(
        "critic_node",
        _retry_router,
        {
            "retry": "planner_retry_transition",
            "continue": END,
        },
    )
    g.add_edge("planner_retry_transition", "research_planner_node")

    return g.compile(checkpointer=checkpointer)
