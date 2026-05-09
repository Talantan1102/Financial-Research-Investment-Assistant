"""build_chat_graph v0.9 — supervisor topology with Q4 E memory and PG checkpointer.

Topology (per spec § 4.1):

    START
      ↓
    context_node       (Q4 E: tool dedup + token-guard summarize)
      ↓
    planner_node       (constrained LLM + tool_choice + parallelizable + escalate)
      ↓ _route_after_planner
      ├→ skill_load_node    (load L2+L3a skill content → loop back to planner)  [Plan 2a]
      │     ↓
      │   planner_node
      ├→ resource_load_node (append single L3a resource → loop back to planner) [Plan 2a]
      │     ↓
      │   planner_node
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
from app.orchestration.context_node import (
    context_node,
    handle_resource_load_action,
    handle_skill_load_action,
)
from app.orchestration.nodes import planner_node, responder_node, tool_node
from app.services.tool_result_cache import ToolResultCache
from app.skills.skill_loader import SkillLoader
from app.tools.registry import ToolRegistry


def _route_after_planner(
    state: ChatState,
) -> Literal["tool_node", "responder_node", "skill_load_node", "resource_load_node"]:
    if state.plan is None:
        return "responder_node"
    if state.plan.load_skill:
        return "skill_load_node"
    if state.plan.load_resource:
        return "resource_load_node"
    if state.plan.direct_response or not state.plan.tool_calls:
        return "responder_node"
    return "tool_node"


async def skill_load_node(state: ChatState, *, loader: SkillLoader) -> dict[str, Any]:
    """Inject L2 + L3a content for skill name in plan.load_skill.

    Clears plan after loading so the planner re-evaluates with the new skill context.
    """
    assert state.plan is not None  # guarded by _route_after_planner
    new_state = handle_skill_load_action(state, state.plan, loader)
    return {"skill_context": new_state.skill_context, "plan": None}


async def resource_load_node(state: ChatState, *, loader: SkillLoader) -> dict[str, Any]:
    """Append a single L3a resource to existing skill context.

    Clears plan after loading so the planner re-evaluates with the new resource.
    """
    assert state.plan is not None  # guarded by _route_after_planner
    new_state = handle_resource_load_action(state, state.plan, loader)
    return {"skill_context": new_state.skill_context, "plan": None}


def build_chat_graph(
    planner: ChatPlanner,
    responder: Responder,
    registry: ToolRegistry,
    memory: Memory,
    cache: ToolResultCache,
    *,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    skill_loader: SkillLoader | None = None,  # NEW Plan 2a
) -> CompiledStateGraph[Any, Any, Any, Any]:
    """Assemble and compile the chat LangGraph StateGraph (v0.9 supervisor topology).

    Graph topology::

        START → context_node → planner_node → [_route_after_planner] → tool_node → responder_node → END
                                                                       → responder_node → END
                                                                       → skill_load_node → planner_node  (Plan 2a)
                                                                       → resource_load_node → planner_node (Plan 2a)

    Args:
        planner:      ChatPlanner instance deciding which tools to call.
        responder:    Responder instance synthesising the final reply.
        registry:     ToolRegistry with all available tools.
        memory:       Memory implementation for Q4 E context management.
        cache:        ToolResultCache for dedup and parallel dispatch.
        checkpointer: Optional PG (or any BaseCheckpointSaver) for cross-turn persistence.
                      Pass None for a stateless in-memory graph (tests / eval).
        skill_loader: Optional SkillLoader for Plan 2a skill-routing nodes.
                      When None the skill_load_node / resource_load_node are not registered
                      and the legacy graph topology is preserved for backward compat.

    Returns:
        A compiled LangGraph :class:`CompiledStateGraph` ready for .ainvoke / .astream_events.
    """
    g: StateGraph[Any, Any, Any, Any] = StateGraph(ChatState)

    g.add_node("context_node", partial(context_node, memory=memory))
    g.add_node("planner_node", partial(planner_node, planner=planner))
    g.add_node("tool_node", partial(tool_node, registry=registry, cache=cache))
    g.add_node("responder_node", partial(responder_node, responder=responder))

    # Plan 2a — skill load nodes (loop back to planner after injecting context)
    if skill_loader is not None:
        g.add_node("skill_load_node", partial(skill_load_node, loader=skill_loader))
        g.add_node("resource_load_node", partial(resource_load_node, loader=skill_loader))

    g.add_edge(START, "context_node")
    g.add_edge("context_node", "planner_node")

    edge_map: dict[str, str] = {
        "tool_node": "tool_node",
        "responder_node": "responder_node",
    }
    if skill_loader is not None:
        edge_map["skill_load_node"] = "skill_load_node"
        edge_map["resource_load_node"] = "resource_load_node"

    g.add_conditional_edges("planner_node", _route_after_planner, edge_map)
    g.add_edge("tool_node", "responder_node")

    if skill_loader is not None:
        g.add_edge("skill_load_node", "planner_node")  # loop back
        g.add_edge("resource_load_node", "planner_node")

    g.add_edge("responder_node", END)

    return g.compile(checkpointer=checkpointer)
