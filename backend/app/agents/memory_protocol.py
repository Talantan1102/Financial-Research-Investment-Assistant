"""Memory Protocol — DI hook for chat in-session + cross-session memory.

v0.9 (Plan 1) ships ``InSessionMemory`` (Q4 E: full + tool-result dedup +
token-guard summarize).  C.5 will replace with ``HierarchicalMemory`` (D
MemGPT-style three-tier).  Both implementations satisfy this Protocol.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.agents.schemas import ChatState, ToolResult


@runtime_checkable
class Memory(Protocol):
    """Chat agent memory interface."""

    def dedup_tool_results(self, results: list[ToolResult]) -> list[ToolResult]:
        """Collapse same (tool_name, args_hash) to keep only the latest (C1)."""
        ...

    def needs_summarize(self, state: ChatState, max_tokens: int) -> bool:
        """True when token-guard threshold (default 80%) is reached."""
        ...

    async def summarize(self, state: ChatState) -> str:
        """LLM-summarize history beyond recent K turns; returns summary text."""
        ...

    async def load_for_turn(self, session_id: str) -> ChatState:
        """Load state from persistence (PG-backed by Plan 1)."""
        ...

    async def save_after_turn(self, state: ChatState) -> None:
        """Persist state after a turn."""
        ...
