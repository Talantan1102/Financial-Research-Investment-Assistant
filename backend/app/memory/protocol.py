"""Memory Protocol — DI hook for chat agent's memory layer.

PR #39 ship 的 InSessionMemory 实现 in-session 范畴(Q4 E).
C.5 加 HierarchicalMemory 实现跨 session 范畴(D MemGPT-style).
两者通过 Memory Protocol 互换.

注: PR #39 的 app.agents.memory_protocol.Memory 是 in-session 子集 Protocol,
本文件是其超集. InSessionMemory 通过 stub 方式实现本 Protocol(Plan 1B Task 2).

契约 ref: docs/superpowers/plans/2026-05-11-c5-plan-shared-contracts.md § 2
Spec ref: docs/superpowers/specs/2026-05-10-c5-cross-session-memory-design.md § 1
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable
from uuid import UUID

if TYPE_CHECKING:
    # Plan 1A 已 ship 的 SQLAlchemy ORM 类
    from app.memory.models import (
        ChatMemoryEdge,
        ChatMemoryEpisode,
        ChatMemoryWorkingBlock,
    )


@runtime_checkable
class Memory(Protocol):
    """Memory interface used by ChatAgent / ResearchAgent.

    HierarchicalMemory(Plan 1-4) 和 InSessionMemory(PR #39 ship) 都实现此 Protocol.
    """

    # === Tier 1 Working Memory(Plan 1B 完整实现) ===

    async def get_working_blocks(self, user_id: UUID) -> dict[str, ChatMemoryWorkingBlock]:
        """Return {block_name: block} for user's persona / scratchpad blocks."""
        ...

    async def core_memory_append(
        self, user_id: UUID, block_name: str, content: str
    ) -> ChatMemoryWorkingBlock | None:
        """Append content to working block. Auto-paging if exceed max_tokens.

        Returns None when block_name='persona' (Task 17: routed to PersonaService).
        """
        ...

    async def core_memory_replace(
        self,
        user_id: UUID,
        block_name: str,
        old_content: str,
        new_content: str,
    ) -> ChatMemoryWorkingBlock | None:
        """Replace exact substring. Raise ValueError if old_content not found.

        Returns None when block_name='persona' (Task 17: routed to PersonaService).
        """
        ...

    # === Tier 2 Archival(Plan 2 写入 / Plan 3 读取) ===

    async def archival_memory_insert(
        self,
        user_id: UUID,
        content: dict[str, Any],
        reasoning: str,
        importance: float,
        evidence_quote: str,  # 算法深度补丁 #2: 防 Agent 幻觉写
        episode_id: UUID,
    ) -> ChatMemoryEdge | None:
        """Write fact to graph. Plan 2 实现完整 pipeline.

        Returns None for NO_OP path (spec § 4 Step 5 完全重复事实).
        """
        ...

    async def archival_memory_search(
        self,
        user_id: UUID,
        query: str,
        k: int = 5,
    ) -> list[ChatMemoryEdge]:
        """3-way hybrid + RRF v2. Plan 3 实现."""
        ...

    async def archival_memory_traverse(
        self,
        user_id: UUID,
        start_label: str,
        hops: int = 2,
        rel_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """On-demand graph traversal via AGE Cypher. Plan 4 实现."""
        ...

    # === Tier 3 Recall(Plan 4 实现, 复用 PR #39 chat_messages 表) ===

    async def recall_memory_search(
        self,
        user_id: UUID,
        query: str,
        k: int = 5,
    ) -> list[dict[str, Any]]:
        """Semantic search on chat_messages history. Plan 4 实现."""
        ...

    # === 持久化 episodes(Plan 1B 完整实现) ===

    async def write_episode(
        self,
        user_id: UUID,
        session_id: UUID,
        episode_index: int,
        user_message: str,
        agent_response: str,
        source_kind: str = "chat_turn",
    ) -> ChatMemoryEpisode:
        """Path A 写入路径 step 1: episode 入库, extracted_at=NULL."""
        ...

    async def write_explicit_episode(
        self,
        user_id: UUID,
        session_id: UUID,
        episode_index: int,
        user_message: str,
        agent_response: str,
        source_kind: str = "agent_explicit",
    ) -> ChatMemoryEpisode:
        """原子创建已 claim、永久不由 Path B 扫描的显式写 episode。"""
        ...

    async def finalize_explicit_episode(
        self, episode_id: UUID, agent_response: str, outcome: str
    ) -> None:
        """记录显式写 episode 的 completed/failed/cancelled 终态。"""
        ...

    async def memory_index_summary(self, user_id: UUID) -> dict[str, Any]:
        """返回无正文的 MEMORY.md 等价 DB 索引投影。"""
        ...

    async def get_unextracted_episodes(
        self, user_id: UUID, limit: int = 100
    ) -> list[ChatMemoryEpisode]:
        """Path B end-of-session batch 用. Plan 5 batch extractor 调用."""
        ...

    async def mark_episode_extracted(
        self,
        episode_id: UUID,
        extracted_by: str,  # 'agent' / 'eos_batch' / 'manual'
        extraction_metadata: dict[str, Any],
    ) -> None:
        """Step 8: 抽取完成标记."""
        ...
