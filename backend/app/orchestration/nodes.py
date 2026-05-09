"""LangGraph node functions bridging state-graph machinery to typed-actor agents.

Each async node function receives the current GraphState and an injected
collaborator (agent or registry), executes the synchronous/async step, and
returns a plain dict of state updates that LangGraph merges back into the
graph state.

v0.9.x fix — sync agent steps wrapped in ``asyncio.to_thread`` so blocking
LLM calls never stall the FastAPI event loop driving SSE streaming.

v0.9 tool_node — asyncio.gather parallel dispatch + ToolResultCache + error recording.
  A2: parallelizable=True runs all tool_calls concurrently via asyncio.gather.
  B3: results sourced from ToolResultCache; cache hit sets ToolResult.cached=True.
  C2: per-tool exceptions are caught and recorded as ToolResult(success=False).

Usage pattern (Task 10):

    graph.add_node("planner", partial(planner_node, planner=chat_planner))
    graph.add_node("tools",   partial(tool_node,    registry=tool_registry, cache=cache, user_id=uid))
    graph.add_node("respond", partial(responder_node, responder=responder))
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

from app.agents.chat_planner import ChatPlanner
from app.agents.responder import Responder
from app.agents.schemas import GraphState, ToolCall, ToolResult
from app.services.tool_result_cache import CacheHit, ToolResultCache
from app.skills.script_schemas import SkillScriptArgs, SkillScriptRef
from app.skills.skill_executor import SkillExecutor
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


async def planner_node(state: GraphState, *, planner: ChatPlanner) -> dict[str, Any]:
    """Run ChatPlanner.run and return its state_update dict.

    v0.9: delegates to planner.run(state) (async, returns dict directly).

    Args:
        state:   Current LangGraph GraphState.
        planner: Injected ChatPlanner instance (keyword-only for functools.partial safety).

    Returns:
        dict containing at least ``{"plan": Plan}``.
    """
    return await planner.run(state)


async def tool_node(
    state: GraphState,
    *,
    registry: ToolRegistry,
    cache: ToolResultCache,
    user_id: str | None = None,
    skill_executor: SkillExecutor | None = None,  # Plan 2b: execute_script branch
    sse_emit: Callable[[dict[str, Any]], None] | None = None,  # Plan 2b: SSE events
) -> dict[str, Any]:
    """Execute tool_calls per plan. Parallel if plan.parallelizable.

    v0.9 changes (A2/B3/C2):
      - Accepts ``cache`` (ToolResultCache) and ``user_id`` kwargs.
      - parallelizable=True: dispatches all calls via asyncio.gather.
      - Cache hits set ToolResult.cached=True.
      - Per-tool exceptions are caught and recorded as ToolResult(success=False).

    Plan 2b changes (S6/S7):
      - Accepts ``skill_executor`` (SkillExecutor) and ``sse_emit`` kwargs.
      - Dispatches script_calls via skill_executor.execute().
      - Emits skill_execute_start / skill_execute_end / skill_execute_error SSE events.

    Args:
        state:          Current LangGraph GraphState.
        registry:       Injected ToolRegistry instance.
        cache:          Injected ToolResultCache instance.
        user_id:        Override user id for cache namespacing (defaults to state.user_id).
        skill_executor: Optional SkillExecutor for execute_script branch (Plan 2b).
        sse_emit:       Optional SSE emit callback for skill_execute events (Plan 2b).

    Returns:
        ``{"tool_results": [ToolResult, ...]}`` accumulating prior results.
    """
    results: list[ToolResult] = []

    # --- existing tool_calls branch ---
    if state.plan is not None and state.plan.tool_calls:
        user = user_id or state.user_id
        coroutines = [_dispatch_one(tc, registry, cache, user) for tc in state.plan.tool_calls]

        if state.plan.parallelizable:
            results = list(await asyncio.gather(*coroutines, return_exceptions=False))
        else:
            for c in coroutines:
                results.append(await c)

    # --- Plan 2b: execute_script branch ---
    if state.plan is not None and state.plan.script_calls and skill_executor is not None:
        for sc in state.plan.script_calls:
            if sse_emit:
                sse_emit(
                    {
                        "event": "skill_execute_start",
                        "data": {"skill": sc.skill, "script": sc.script, "args": sc.args},
                    }
                )
            ref = SkillScriptRef(skill_name=sc.skill, script_path=sc.script)
            args_obj = SkillScriptArgs(payload=sc.args)
            result = await skill_executor.execute(ref=ref, args=args_obj)
            if result.ok:
                if sse_emit:
                    sse_emit(
                        {
                            "event": "skill_execute_end",
                            "data": {
                                "skill": sc.skill,
                                "script": sc.script,
                                "stdout_json": result.stdout_json,
                                "elapsed_s": result.elapsed_s,
                            },
                        }
                    )
                results.append(
                    ToolResult(
                        tool_name="skill_script",
                        args={"skill": sc.skill, "script": sc.script, "args": sc.args},
                        output=result.stdout_json,
                        success=True,
                        error=None,
                        latency_ms=int(result.elapsed_s * 1000),
                        tool_call_data={
                            "kind": "skill_script",
                            "skill": sc.skill,
                            "script": sc.script,
                            "stderr_text": result.stderr_text,
                        },
                    )
                )
            else:
                if sse_emit:
                    sse_emit(
                        {
                            "event": "skill_execute_error",
                            "data": {
                                "skill": sc.skill,
                                "script": sc.script,
                                "error_kind": result.error.kind if result.error else "unknown",
                                "error_message": result.error.message if result.error else "",
                                "stderr_text": result.stderr_text,
                            },
                        }
                    )
                err_msg = (
                    f"{result.error.kind}: {result.error.message}"
                    if result.error
                    else "unknown error"
                )
                results.append(
                    ToolResult(
                        tool_name="skill_script",
                        args={"skill": sc.skill, "script": sc.script, "args": sc.args},
                        output=None,
                        success=False,
                        error=err_msg,
                        latency_ms=int(result.elapsed_s * 1000),
                        tool_call_data={
                            "kind": "skill_script",
                            "skill": sc.skill,
                            "script": sc.script,
                            "error_kind": result.error.kind if result.error else "unknown",
                            "stderr_text": result.stderr_text,
                        },
                    )
                )

    return {"tool_results": list(state.tool_results) + results}


async def _dispatch_one(
    tc: ToolCall,
    registry: ToolRegistry,
    cache: ToolResultCache,
    user_id: str,
) -> ToolResult:
    """Single tool dispatch: cache lookup → execute → error wrap.

    B3: delegates to cache.get_or_compute; HIT sets cached=True.
    C2: any exception from cache/tool is caught and returned as success=False.
    """
    started = time.perf_counter()

    tool = registry.get(tc.tool_name) if tc.tool_name in registry._tools else None
    if tool is None:
        return ToolResult(
            tool_name=tc.tool_name,
            args=tc.args,
            output=None,
            success=False,
            error=f"tool '{tc.tool_name}' not registered",
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    async def _compute() -> dict[str, Any]:
        validated = tool.args_schema.model_validate(tc.args)
        return await tool.run(validated)

    try:
        result, hit = await cache.get_or_compute(
            user_id=user_id,
            tool_name=tc.tool_name,
            args=tc.args,
            compute_fn=_compute,
        )
        return ToolResult(
            tool_name=tc.tool_name,
            args=tc.args,
            output=result,
            success=True,
            error=None,
            latency_ms=int((time.perf_counter() - started) * 1000),
            cached=(hit == CacheHit.HIT),
        )
    except Exception as e:  # C2: tool failure → record, don't re-raise
        logger.exception("tool %s failed", tc.tool_name)
        return ToolResult(
            tool_name=tc.tool_name,
            args=tc.args,
            output=None,
            success=False,
            error=str(e),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


async def responder_node(state: GraphState, *, responder: Responder) -> dict[str, Any]:
    """Run Responder.run and return its state_update dict.

    v0.9: delegates to responder.run(state) (async, returns dict directly).

    Args:
        state:     Current LangGraph GraphState.
        responder: Injected Responder instance.

    Returns:
        dict containing at least ``{"final_response": str}``.
    """
    return await responder.run(state)
