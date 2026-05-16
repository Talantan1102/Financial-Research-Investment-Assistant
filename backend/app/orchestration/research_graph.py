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
# v1.x — writer retry edge on factuality < threshold (spec § 7.2).
#
# Replaces v0.8.5 planner retry. Rationale: with Validator-gated planner,
# "wrong plan" can't reach Critic. The real failure mode worth retrying is
# Writer using data sloppily → factuality < 7.0. Writer retry is expensive
# (long LLM call), so only 1 retry allowed (vs 2 for planner in v0.8.5).
#
# v1.x A5a: added valuation_consistency OR trigger — narrative that masks
# cross-check divergence (未提偏离原因 / 未引用 diagnosis) also fires retry.
# ---------------------------------------------------------------------------

_FACTUALITY_THRESHOLD = 7.0
_VALUATION_CONSISTENCY_THRESHOLD = 7.0  # v1.x A5a
_MAX_WRITER_RETRY = 1


def _writer_retry_router(state: ResearchState) -> Literal["retry", "continue"]:
    """Conditional edge after critic_node — retry writer iff (factuality OR
    valuation_consistency) score is below threshold AND retry budget remains.

    v1.x A5a: adds valuation_consistency trigger — narrative that fails to
    reflect cross-check signals (掩盖打架 / 未提偏离 / 未引用 diagnosis) causes
    a writer retry so the report is rewritten with explicit feedback.
    """
    if state.critic_report is None:
        return "continue"
    if state.writer_retry_count >= _MAX_WRITER_RETRY:
        return "continue"

    fact_score = state.critic_report.get_score("factuality")
    valuation_score = state.critic_report.get_score("valuation_consistency")

    fact_trigger = fact_score is not None and fact_score < _FACTUALITY_THRESHOLD
    valuation_trigger = (
        valuation_score is not None and valuation_score < _VALUATION_CONSISTENCY_THRESHOLD
    )
    if fact_trigger or valuation_trigger:
        return "retry"
    return "continue"


def _writer_retry_state_update(state: ResearchState) -> dict[str, Any]:
    """State diff for retry transition: bump count + capture critic evidence
    (factuality + valuation_consistency, joined, capped at 300 chars).

    v1.x A5a: feedback includes both factuality and valuation_consistency
    evidence (when present) so the writer sees both dimensions on retry.
    """
    pieces: list[str] = []
    if state.critic_report is not None:
        for dim in state.critic_report.dimensions:
            if dim.dimension in ("factuality", "valuation_consistency"):
                pieces.append(f"[{dim.dimension}={dim.score:.1f}] {dim.evidence}")
    feedback = " | ".join(pieces)
    return {
        "writer_retry_count": state.writer_retry_count + 1,
        "writer_critic_feedback": feedback[:300],
    }


async def _writer_retry_transition_node(state: ResearchState) -> dict[str, Any]:
    """Lightweight node between critic_node and writer_node on retry path.

    Separation of concerns: state bookkeeping belongs to graph, not Writer.
    """
    return _writer_retry_state_update(state)


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
    # v1.x — retry transition node updates state.writer_retry_count +
    # writer_critic_feedback before looping back to writer_node.
    g.add_node("writer_retry_transition", _writer_retry_transition_node)

    g.add_edge(START, "research_planner_node")
    g.add_edge("research_planner_node", "data_collector_node")
    g.add_edge("data_collector_node", "analyst_node")
    g.add_edge("analyst_node", "writer_node")
    g.add_edge("writer_node", "critic_node")
    # v1.x retry: critic_node → (retry → writer_retry_transition → writer_node) | (continue → END)
    g.add_conditional_edges(
        "critic_node",
        _writer_retry_router,
        {
            "retry": "writer_retry_transition",
            "continue": END,
        },
    )
    g.add_edge("writer_retry_transition", "writer_node")

    return g.compile(checkpointer=checkpointer)
