"""Top-level v0.5 research mode StateGraph builder."""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agents.analyst import Analyst
from app.agents.critic import Critic
from app.agents.data_collector import DataCollector
from app.agents.research_planner import ResearchPlanner
from app.agents.schemas import ResearchState
from app.agents.writer import Writer
from app.orchestration.checkpointer import make_chat_checkpointer
from app.orchestration.critic_subgraph import build_critic_subgraph
from app.orchestration.research_nodes import (
    analyst_node,
    data_collector_node,
    research_planner_node,
    writer_node,
)


def build_research_graph(
    planner: ResearchPlanner,
    collector: DataCollector,
    analyst: Analyst,
    writer: Writer,
    critic: Critic,
    *,
    db_path: Path | None = None,
) -> Any:
    """Assemble and compile the v0.5 research LangGraph StateGraph.

    Graph topology::

        START → research_planner_node → data_collector_node → analyst_node
              → writer_node → critic_node → END

    Args:
        planner:   ResearchPlanner that decomposes the user query into subtasks.
        collector: DataCollector that executes tool calls in parallel.
        analyst:   Analyst that derives insights from tool results.
        writer:    Writer that synthesises the final research report.
        critic:    Critic subagent that scores the report on 5 dimensions.
        db_path:   Optional path to a SQLite file for checkpointing.
                   Pass None for a stateless in-memory graph (tests / eval).

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

    g.add_edge(START, "research_planner_node")
    g.add_edge("research_planner_node", "data_collector_node")
    g.add_edge("data_collector_node", "analyst_node")
    g.add_edge("analyst_node", "writer_node")
    g.add_edge("writer_node", "critic_node")
    g.add_edge("critic_node", END)

    checkpointer = make_chat_checkpointer(db_path) if db_path else None
    return g.compile(checkpointer=checkpointer)
