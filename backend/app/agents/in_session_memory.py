"""InSessionMemory — Q4 E implementation.

Strategy (per spec § 4.1 § 2.2 update):
  - Full history kept by default (low-cost in-session)
  - Cross-turn tool result dedup (C1): same (tool_name, args_hash) → keep latest
  - Token-guard summarize (B1): when est. tokens >= 80% of max, LLM-summarize the
    pre-K-turns history into ``state.history_summary`` and drop pre-K turns
  - Recent K = 4 turns retained verbatim post-summarize

Note: entity / preference / open-question extraction is deferred to escalate
time (Plan 3 deliverable per § 2.2 update).  This class only handles in-session
context compaction.

Schema note: existing ToolResult uses ``args: dict[str, Any]`` (not args_json: str)
and ``success: bool`` (not ok: bool).  _sig() serialises the dict for stable hashing.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import TYPE_CHECKING, Final

from app.agents.schemas import ChatState, HistoryMessage, ToolResult

if TYPE_CHECKING:
    from app.services.llm_service import LLMService

DEFAULT_MAX_TOKENS: Final[int] = 24_000
DEFAULT_THRESHOLD: Final[float] = 0.80
RECENT_K_TURNS: Final[int] = 4
APPROX_CHARS_PER_TOKEN: Final[float] = 2.5  # CJK-heavy mix; calibrated v0.7


def _approx_tokens_chars(total_chars: int) -> int:
    return int(total_chars / APPROX_CHARS_PER_TOKEN)


def _sig(tool_name: str, args: dict) -> str:
    """Cross-turn dedup signature: (tool_name, sorted-arg-hash)."""
    try:
        normalized = json.dumps(args, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError):
        normalized = str(args)
    return f"{tool_name}:{hashlib.sha256(normalized.encode()).hexdigest()[:16]}"


class InSessionMemory:
    """Default Memory implementation for v0.9 chat (Q4 E)."""

    def __init__(
        self,
        llm: LLMService | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        threshold: float = DEFAULT_THRESHOLD,
        recent_k: int = RECENT_K_TURNS,
    ) -> None:
        self._llm = llm
        self._max = max_tokens
        self._threshold = threshold
        self._recent_k = recent_k

    def dedup_tool_results(self, results: list[ToolResult]) -> list[ToolResult]:
        """Keep only the latest ToolResult per (tool_name, args) signature."""
        latest_by_sig: dict[str, ToolResult] = {}
        for r in results:
            latest_by_sig[_sig(r.tool_name, r.args)] = r
        return list(latest_by_sig.values())

    def needs_summarize(self, state: ChatState, max_tokens: int = 0) -> bool:
        cap = max_tokens or self._max
        total_chars = sum(len(m.content) for m in state.history)
        if state.history_summary:
            total_chars += len(state.history_summary)
        return _approx_tokens_chars(total_chars) >= self._threshold * cap

    async def summarize(self, state: ChatState) -> str:
        if self._llm is None:
            raise RuntimeError(
                "InSessionMemory.summarize requires an LLMService injected via __init__"
            )
        if len(state.history) <= self._recent_k:
            return state.history_summary or ""
        old = state.history[: -self._recent_k]
        prompt = _build_summarize_prompt(old, state.history_summary)
        # C15: offload the blocking sync LLM round-trip off the event loop so
        # summarization on every turn doesn't stall the SSE stream.
        resp = await asyncio.to_thread(self._llm.chat, prompt=prompt, tier="fast", schema=None)
        return resp.content.strip()

    async def load_for_turn(self, session_id: str) -> ChatState:
        raise NotImplementedError(
            "Plan 1 calls load_for_turn() through ChatSessionRepo, not Memory directly."
        )

    async def save_after_turn(self, state: ChatState) -> None:
        raise NotImplementedError(
            "Plan 1 calls save_after_turn() through ChatSessionRepo, not Memory directly."
        )

    # === C.5 Plan 1B: Protocol 兼容 stub(InSessionMemory 不实现 cross-session) ===
    # 这些 method 的具体实现在 HierarchicalMemory(C.5 Plan 1B+).
    # InSessionMemory 提供 stub 让 isinstance(InSessionMemory(...), app.memory.protocol.Memory)
    # 返回 True, 保持 Protocol 兼容. 实际 cross-session 操作走 HierarchicalMemory.

    async def get_working_blocks(self, user_id):  # type: ignore[no-untyped-def]
        raise NotImplementedError(
            "InSessionMemory 是 in-session memory(PR #39 Q4 E), "
            "Tier 1 working blocks 由 HierarchicalMemory(C.5 Plan 1B+)实现."
        )

    async def core_memory_append(self, user_id, block_name, content):  # type: ignore[no-untyped-def]
        raise NotImplementedError("see HierarchicalMemory.core_memory_append")

    async def core_memory_replace(  # type: ignore[no-untyped-def]
        self, user_id, block_name, old_content, new_content
    ):
        raise NotImplementedError("see HierarchicalMemory.core_memory_replace")

    async def archival_memory_insert(  # type: ignore[no-untyped-def]
        self, user_id, content, reasoning, importance, evidence_quote, episode_id
    ):
        raise NotImplementedError("see HierarchicalMemory.archival_memory_insert (Plan 2)")

    async def archival_memory_search(self, user_id, query, k=5):  # type: ignore[no-untyped-def]
        raise NotImplementedError("see HierarchicalMemory.archival_memory_search (Plan 3)")

    async def archival_memory_traverse(  # type: ignore[no-untyped-def]
        self, user_id, start_label, hops=2, rel_types=None
    ):
        raise NotImplementedError("see HierarchicalMemory.archival_memory_traverse (Plan 4)")

    async def recall_memory_search(self, user_id, query, k=5):  # type: ignore[no-untyped-def]
        raise NotImplementedError("see HierarchicalMemory.recall_memory_search (Plan 4)")

    async def write_episode(  # type: ignore[no-untyped-def]
        self,
        user_id,
        session_id,
        episode_index,
        user_message,
        agent_response,
        source_kind="chat_turn",
    ):
        raise NotImplementedError("see HierarchicalMemory.write_episode")

    async def get_unextracted_episodes(self, user_id, limit=100):  # type: ignore[no-untyped-def]
        raise NotImplementedError("see HierarchicalMemory.get_unextracted_episodes")

    async def mark_episode_extracted(  # type: ignore[no-untyped-def]
        self, episode_id, extracted_by, extraction_metadata
    ):
        raise NotImplementedError("see HierarchicalMemory.mark_episode_extracted")


def _build_summarize_prompt(history: list[HistoryMessage], prior_summary: str | None) -> str:
    """Concise summarization prompt; produces 200-400 char Chinese summary."""
    lines = ["请把下面的对话历史浓缩成 200-400 字的中文摘要,保留:"]
    lines.append("- 用户讨论过的标的 / 公司 / 概念(及代码,如 ICBC 601398.SH)")
    lines.append("- 用户表达的偏好 / 风险倾向 / 关注指标")
    lines.append("- 用户提出但 chat 没回答的疑问")
    lines.append("- 关键 tool 调用及其结果(用 1 句话)\n")
    if prior_summary:
        lines.append(f"先前摘要:{prior_summary}\n")
    lines.append("对话历史:")
    for m in history:
        lines.append(f"[{m.turn_index}] {m.role}: {m.content[:300]}")
    lines.append("\n摘要:")
    return "\n".join(lines)
