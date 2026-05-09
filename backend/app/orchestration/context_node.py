"""context_node — Q4 E memory entry into chat_graph (per spec § 4.1).

Responsibilities (in order):
  1. Cross-turn tool-result dedup (C1) via Memory.dedup_tool_results
  2. Token-guard check (B1); if >= threshold, LLM-summarize old turns and drop
     them, retaining only recent K turns

History loading from PG is performed by the chat router before invoking the
graph (see Task 18); ``context_node`` operates only on the in-memory state.
"""

from __future__ import annotations

from typing import Any

from app.agents.in_session_memory import RECENT_K_TURNS
from app.agents.memory_protocol import Memory
from app.agents.schemas import ChatState


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
