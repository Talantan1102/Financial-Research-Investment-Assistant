"""context_node — Q4 E memory entry into chat_graph (per spec § 4.1).

Responsibilities (in order):
  1. Cross-turn tool-result dedup (C1) via Memory.dedup_tool_results
  2. Token-guard check (B1); if >= threshold, LLM-summarize old turns and drop
     them, retaining only recent K turns

History loading from PG is performed by the chat router before invoking the
graph (see Task 18); ``context_node`` operates only on the in-memory state.
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.in_session_memory import RECENT_K_TURNS
from app.agents.memory_protocol import Memory
from app.agents.schemas import ChatState, Plan
from app.skills import (
    NestedDepthExceededError,
    ResourceTooLargeError,
    SkillLoaderError,
)
from app.skills.skill_loader import SkillLoader

log = logging.getLogger(__name__)


def _format_resource_block(r: Any) -> str:
    return (
        f"\n\n## Resource: {r.relative_path} ({r.content_type}, {r.size_bytes} bytes)\n\n"
        f"```{r.content_type}\n{r.content}\n```"
    )


def _format_skill_bundle(skill_md_body: str, resources: list[Any]) -> str:
    parts: list[str] = [skill_md_body]
    for r in resources:
        parts.append(_format_resource_block(r))
    return "".join(parts)


def handle_skill_load_action(
    state: ChatState,
    plan: Plan,
    loader: SkillLoader,
) -> ChatState:
    """Handle planner's load_skill — populate ChatState.skill_context.

    Idempotent: if skill already loaded, returns state unchanged.
    Graceful degrade on error: state unchanged + warning log.
    S10: skill content is text-only — no tool dispatch.
    """
    name = plan.load_skill
    if not name:
        return state
    if name in state.skill_context:
        return state

    try:
        result = loader.load_skill(name)
    except (SkillLoaderError, ResourceTooLargeError, NestedDepthExceededError) as e:
        log.warning("load_skill(%s) failed: %s", name, e)
        return state

    bundle = _format_skill_bundle(result.skill_md_content, result.resources)
    new_ctx = dict(state.skill_context)
    new_ctx[name] = bundle
    return state.model_copy(update={"skill_context": new_ctx})


def handle_resource_load_action(
    state: ChatState,
    plan: Plan,
    loader: SkillLoader,
) -> ChatState:
    """Handle planner's load_resource — append resource to existing skill bundle."""
    spec = plan.load_resource
    if not spec or not isinstance(spec, dict):
        return state
    skill = spec.get("skill")
    ref = spec.get("ref")
    if not skill or not ref:
        return state
    if skill not in state.skill_context:
        log.warning(
            "load_resource on unloaded skill %s — planner should load_skill first",
            skill,
        )
        return state

    try:
        r = loader.load_resource(skill, ref)
    except (SkillLoaderError, ResourceTooLargeError) as e:
        log.warning("load_resource(%s, %s) failed: %s", skill, ref, e)
        return state

    appended = state.skill_context[skill] + _format_resource_block(r)
    new_ctx = dict(state.skill_context)
    new_ctx[skill] = appended
    return state.model_copy(update={"skill_context": new_ctx})


async def context_node(state: ChatState, *, memory: Memory) -> dict[str, Any]:
    """Apply E memory transformations to state. Returns dict for LangGraph state update."""
    update: dict[str, Any] = {}

    # 1. tool result cross-turn dedup
    deduped = memory.dedup_tool_results(state.tool_results)
    if len(deduped) != len(state.tool_results):
        update["tool_results"] = deduped

    # 2. token-guard summarize
    if memory.needs_summarize(state, max_tokens=0):
        summary = await memory.summarize(state)
        update["history_summary"] = summary
        update["history"] = state.history[-RECENT_K_TURNS:]

    return update
