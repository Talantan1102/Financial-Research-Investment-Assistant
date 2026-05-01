"""build_chat_graph — wire ChatPlanner + Responder + ToolRegistry into a LangGraph StateGraph.

Graph topology:
  START → planner_node → [conditional] → tool_node → responder_node → END
                                       → responder_node → END  (direct_response or no plan)
"""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.chat_planner import ChatPlanner
from app.agents.responder import Responder
from app.agents.schemas import GraphState
from app.orchestration.checkpointer import make_chat_checkpointer
from app.orchestration.nodes import planner_node, responder_node, tool_node
from app.tools.registry import ToolRegistry


def _route_after_planner(state: GraphState) -> Literal["tool_node", "responder_node"]:
    """Routing function: direct to tool_node if tool_calls exist, else responder_node.

    Handles two cases where responder is called directly:
    - plan is None (planner failed gracefully)
    - plan.direct_response is True (no tools needed)
    - plan.tool_calls is empty (defensive)
    """
    if state.plan is None:
        return "responder_node"  # planner failed gracefully — let responder explain
    return "tool_node" if state.plan.tool_calls else "responder_node"


def build_chat_graph(
    planner: ChatPlanner,
    responder: Responder,
    registry: ToolRegistry,
    *,
    db_path: Path | None = None,
) -> CompiledStateGraph[Any, Any, Any, Any]:
    """Assemble and compile the chat LangGraph StateGraph.

    Graph topology::

        START → planner_node → [_route_after_planner] → tool_node → responder_node → END
                                                       → responder_node → END

    Args:
        planner:  ChatPlanner instance deciding which tools to call.
        responder: Responder instance synthesising the final reply.
        registry: ToolRegistry with all available tools.
        db_path:  Optional path to a SQLite file for checkpointing.
                  Pass None for a stateless in-memory graph (tests / eval).

    Returns:
        A compiled LangGraph :class:`CompiledStateGraph` ready for .ainvoke / .astream_events.
    """
    g: StateGraph[Any, Any, Any, Any] = StateGraph(GraphState)
    g.add_node("planner_node", partial(planner_node, planner=planner))
    g.add_node("tool_node", partial(tool_node, registry=registry))
    g.add_node("responder_node", partial(responder_node, responder=responder))

    g.add_edge(START, "planner_node")
    g.add_conditional_edges(
        "planner_node",
        _route_after_planner,
        {
            "tool_node": "tool_node",
            "responder_node": "responder_node",
        },
    )
    g.add_edge("tool_node", "responder_node")
    g.add_edge("responder_node", END)

    checkpointer = make_chat_checkpointer(db_path) if db_path else None
    return g.compile(checkpointer=checkpointer)
