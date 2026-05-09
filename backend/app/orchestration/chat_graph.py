"""build_chat_graph v0.9 — supervisor topology with Q4 E memory and PG checkpointer.

Topology (per spec § 4.1):

    START
      ↓
    context_node       (Q4 E: tool dedup + token-guard summarize)
      ↓
    planner_node       (constrained LLM + tool_choice + parallelizable + escalate)
      ↓ _route_after_planner
      ├→ tool_node     (asyncio.gather + ToolResultCache + error recording)
      │     ↓
      │   responder_node
      │     ↓
      │   END
      └→ responder_node  (direct response, no tools)
              ↓
            END
"""

from __future__ import annotations

from functools import partial
from typing import Any, Literal

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.chat_planner import ChatPlanner
from app.agents.memory_protocol import Memory
from app.agents.responder import Responder
from app.agents.schemas import ChatState
from app.orchestration.context_node import context_node
from app.orchestration.nodes import planner_node, responder_node, tool_node
from app.services.tool_result_cache import ToolResultCache
from app.tools.registry import ToolRegistry


def _route_after_planner(state: ChatState) -> Literal["tool_node", "responder_node"]:
    if state.plan is None:
        return "responder_node"
    if state.plan.direct_response or not state.plan.tool_calls:
        return "responder_node"
    return "tool_node"


def build_chat_graph(
    planner: ChatPlanner,
    responder: Responder,
    registry: ToolRegistry,
    memory: Memory,
    cache: ToolResultCache,
    *,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> CompiledStateGraph[Any, Any, Any, Any]:
    """Assemble and compile the chat LangGraph StateGraph (v0.9 supervisor topology).

    Graph topology::

        START → context_node → planner_node → [_route_after_planner] → tool_node → responder_node → END
                                                                       → responder_node → END

    Args:
        planner:      ChatPlanner instance deciding which tools to call.
        responder:    Responder instance synthesising the final reply.
        registry:     ToolRegistry with all available tools.
        memory:       Memory implementation for Q4 E context management.
        cache:        ToolResultCache for dedup and parallel dispatch.
        checkpointer: Optional PG (or any BaseCheckpointSaver) for cross-turn persistence.
                      Pass None for a stateless in-memory graph (tests / eval).

    Returns:
        A compiled LangGraph :class:`CompiledStateGraph` ready for .ainvoke / .astream_events.
    """
    g: StateGraph[Any, Any, Any, Any] = StateGraph(ChatState)

    g.add_node("context_node", partial(context_node, memory=memory))
    g.add_node("planner_node", partial(planner_node, planner=planner))
    g.add_node("tool_node", partial(tool_node, registry=registry, cache=cache))
    g.add_node("responder_node", partial(responder_node, responder=responder))

    g.add_edge(START, "context_node")
    g.add_edge("context_node", "planner_node")
    g.add_conditional_edges(
        "planner_node",
        _route_after_planner,
        {"tool_node": "tool_node", "responder_node": "responder_node"},
    )
    g.add_edge("tool_node", "responder_node")
    g.add_edge("responder_node", END)

    return g.compile(checkpointer=checkpointer)
