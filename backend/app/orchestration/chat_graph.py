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

from collections.abc import Hashable
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
from app.orchestration.memory_kb_router_node import (  # Plan 6 (c5)
    RouterFn,
    memory_kb_router_node,
)
from app.orchestration.nodes import planner_node, responder_node, tool_node
from app.services.kb_search_service import KbSearchService  # Plan 6 (c5)
from app.services.tool_result_cache import ToolResultCache
from app.skills.skill_loader import SkillLoader
from app.tools.registry import ToolRegistry


def _approx_tokens(text: str) -> int:
    """1 token ≈ 4 bytes UTF-8 (mixed CJK + English heuristic)."""
    return len(text.encode("utf-8")) // 4


def _route_after_planner(
    state: ChatState,
    *,
    # C6: bound via partial in build_chat_graph so skill/resource nodes are only
    # targeted when they are actually registered in the graph.
    skill_loader_available: bool = False,
) -> Literal["tool_node", "responder_node", "skill_load_node", "resource_load_node"]:
    if state.plan is None:
        return "responder_node"
    if skill_loader_available and state.plan.load_skill:
        return "skill_load_node"
    if skill_loader_available and state.plan.load_resource:
        return "resource_load_node"
    if state.plan.direct_response or not state.plan.tool_calls:
        return "responder_node"
    return "tool_node"


async def skill_load_node(state: ChatState, *, loader: SkillLoader) -> dict[str, Any]:
    """Inject L2 + L3a content for skill name in plan.load_skill.

    Clears plan after loading so the planner re-evaluates with the new skill context.
    Emits a ``skill_load`` SSE event (level=L2) via LangGraph stream writer when in
    a streaming context; safely no-ops otherwise.
    """
    assert state.plan is not None  # guarded by _route_after_planner
    new_state = handle_skill_load_action(state, state.plan, loader)

    name = state.plan.load_skill
    if name and name not in state.skill_context and name in new_state.skill_context:
        loaded_text = new_state.skill_context[name]
        try:
            from langgraph.config import get_stream_writer

            writer = get_stream_writer()
            writer(
                {
                    "type": "skill_load",
                    "name": name,
                    "level": "L2",
                    "size_tokens": _approx_tokens(loaded_text),
                }
            )
        except (RuntimeError, ImportError):
            pass  # not in streaming context

    return {"skill_context": new_state.skill_context, "plan": None}


async def resource_load_node(state: ChatState, *, loader: SkillLoader) -> dict[str, Any]:
    """Append a single L3a resource to existing skill context.

    Clears plan after loading so the planner re-evaluates with the new resource.
    Emits a ``skill_load`` SSE event (level=L3a) via LangGraph stream writer when in
    a streaming context; safely no-ops otherwise.
    """
    assert state.plan is not None  # guarded by _route_after_planner
    new_state = handle_resource_load_action(state, state.plan, loader)

    spec = state.plan.load_resource
    if isinstance(spec, dict):
        skill = spec.get("skill")
        ref = spec.get("ref")
        if skill and ref:
            before = state.skill_context.get(skill, "")
            after = new_state.skill_context.get(skill, "")
            delta = after[len(before) :]
            if delta:
                try:
                    from langgraph.config import get_stream_writer

                    writer = get_stream_writer()
                    writer(
                        {
                            "type": "skill_load",
                            "name": skill,
                            "level": "L3a",
                            "ref": ref,
                            "size_tokens": _approx_tokens(delta),
                        }
                    )
                except (RuntimeError, ImportError):
                    pass  # not in streaming context

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
    kb_search_service: KbSearchService | None = None,  # NEW Plan 6 (c5)
    memory_kb_router_fn: RouterFn | None = None,  # NEW Plan 6 (c5)
) -> CompiledStateGraph[Any, Any, Any, Any]:
    """Assemble and compile the chat LangGraph StateGraph (v0.9 supervisor topology).

    Graph topology::

        START → context_node → [memory_kb_router_node?] → planner_node → [_route_after_planner]
                                                                          → tool_node → responder_node → END
                                                                          → responder_node → END
                                                                          → skill_load_node → planner_node  (Plan 2a)
                                                                          → resource_load_node → planner_node (Plan 2a)

    Args:
        planner:             ChatPlanner instance deciding which tools to call.
        responder:           Responder instance synthesising the final reply.
        registry:            ToolRegistry with all available tools.
        memory:              Memory implementation for Q4 E context management.
        cache:               ToolResultCache for dedup and parallel dispatch.
        checkpointer:        Optional PG (or any BaseCheckpointSaver) for cross-turn persistence.
                             Pass None for a stateless in-memory graph (tests / eval).
        skill_loader:        Optional SkillLoader for Plan 2a skill-routing nodes.
                             When None the skill_load_node / resource_load_node are not registered
                             and the legacy graph topology is preserved for backward compat.
        kb_search_service:   Optional KbSearchService (C.5 Plan 6) — when provided together
                             with ``memory_kb_router_fn`` the supervisor inserts a
                             ``memory_kb_router_node`` between context_node and planner_node
                             (memory vs kb retrieval routing). When None routing is skipped
                             entirely (backward compat for the legacy chat router).
        memory_kb_router_fn: Optional async callable ``str -> RouterDecision`` (C.5 Plan 6).
                             Must be provided together with ``kb_search_service``.

    Returns:
        A compiled LangGraph :class:`CompiledStateGraph` ready for .ainvoke / .astream_events.

    Raises:
        ValueError: when exactly one of ``kb_search_service`` / ``memory_kb_router_fn`` is set
                    (they must be passed as a pair).
    """
    if (kb_search_service is None) != (memory_kb_router_fn is None):
        raise ValueError("kb_search_service and memory_kb_router_fn must be provided together")
    enable_kb_routing = kb_search_service is not None and memory_kb_router_fn is not None

    g: StateGraph[Any, Any, Any, Any] = StateGraph(ChatState)

    g.add_node("context_node", partial(context_node, memory=memory))
    g.add_node("planner_node", partial(planner_node, planner=planner))
    g.add_node("tool_node", partial(tool_node, registry=registry, cache=cache))
    g.add_node("responder_node", partial(responder_node, responder=responder))

    # Plan 2a — skill load nodes (loop back to planner after injecting context)
    if skill_loader is not None:
        g.add_node("skill_load_node", partial(skill_load_node, loader=skill_loader))
        g.add_node("resource_load_node", partial(resource_load_node, loader=skill_loader))

    # Plan 6 (c5) — Memory vs KB router (between context and planner)
    if enable_kb_routing:
        # type narrowing: both are non-None inside this branch
        assert kb_search_service is not None
        assert memory_kb_router_fn is not None
        g.add_node(
            "memory_kb_router_node",
            partial(
                memory_kb_router_node,
                memory=memory,
                kb=kb_search_service,
                router_fn=memory_kb_router_fn,
            ),
        )

    g.add_edge(START, "context_node")
    if enable_kb_routing:
        g.add_edge("context_node", "memory_kb_router_node")
        g.add_edge("memory_kb_router_node", "planner_node")
    else:
        g.add_edge("context_node", "planner_node")

    edge_map: dict[Hashable, str] = {
        "tool_node": "tool_node",
        "responder_node": "responder_node",
    }
    if skill_loader is not None:
        edge_map["skill_load_node"] = "skill_load_node"
        edge_map["resource_load_node"] = "resource_load_node"

    # C6: partial binds skill_loader_available so _route_after_planner never
    # returns a node name that isn't registered in edge_map (avoids KeyError).
    g.add_conditional_edges(
        "planner_node",
        partial(_route_after_planner, skill_loader_available=skill_loader is not None),
        edge_map,
    )
    g.add_edge("tool_node", "responder_node")

    if skill_loader is not None:
        g.add_edge("skill_load_node", "planner_node")  # loop back
        g.add_edge("resource_load_node", "planner_node")

    g.add_edge("responder_node", END)

    return g.compile(checkpointer=checkpointer)
