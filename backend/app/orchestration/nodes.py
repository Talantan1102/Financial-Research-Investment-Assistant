"""LangGraph node functions bridging state-graph machinery to typed-actor agents.

Each async node function receives the current GraphState and an injected
collaborator (agent or registry), executes the synchronous/async step, and
returns a plain dict of state updates that LangGraph merges back into the
graph state.

v0.9.x fix — sync agent steps wrapped in ``asyncio.to_thread`` so blocking
LLM calls never stall the FastAPI event loop driving SSE streaming.

Usage pattern (Task 10):

    graph.add_node("planner", partial(planner_node, planner=chat_planner))
    graph.add_node("tools",   partial(tool_node,    registry=tool_registry))
    graph.add_node("respond", partial(responder_node, responder=responder))
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.agents.chat_planner import ChatPlanner
from app.agents.responder import Responder
from app.agents.schemas import GraphState
from app.tools.registry import ToolRegistry


async def planner_node(state: GraphState, *, planner: ChatPlanner) -> dict[str, Any]:
    """Run ChatPlanner.step and return its state_update dict.

    Args:
        state:   Current LangGraph GraphState.
        planner: Injected ChatPlanner instance (keyword-only for functools.partial safety).

    Returns:
        dict containing at least ``{"plan": Plan}``.
    """
    sr = await asyncio.to_thread(planner.step, state)
    return sr.state_update


async def tool_node(state: GraphState, *, registry: ToolRegistry) -> dict[str, Any]:
    """Execute all tool_calls from state.plan through the ToolRegistry.

    Returns an empty dict when plan is None (e.g. after a direct_response path).

    Args:
        state:    Current LangGraph GraphState.
        registry: Injected ToolRegistry instance.

    Returns:
        ``{"tool_results": [ToolResult, ...]}`` or ``{}`` if no plan.
    """
    if state.plan is None:
        return {}

    results = []
    for call in state.plan.tool_calls:
        results.append(await registry.execute(call))
    return {"tool_results": results}


async def responder_node(state: GraphState, *, responder: Responder) -> dict[str, Any]:
    """Run Responder.step and return its state_update dict.

    Args:
        state:     Current LangGraph GraphState.
        responder: Injected Responder instance.

    Returns:
        dict containing at least ``{"final_response": str}``.
    """
    sr = await asyncio.to_thread(responder.step, state)
    return sr.state_update
