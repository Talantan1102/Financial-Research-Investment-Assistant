"""HierarchicalMemory — C.5 跨 session memory 实现, 替换 InSessionMemory.

contract ref: § 3 HierarchicalMemory class 骨架
spec ref: § 1 整体架构 / § 7 working memory / § 8 cold start

Plan 1B 范围:
- working blocks: get / append / replace
- episodes 持久化: write_episode / get_unextracted_episodes / mark_episode_extracted

Plan 2-4 范围(本文件加 stub):
- archival_memory_insert (Plan 2)
- archival_memory_search (Plan 3)
- archival_memory_traverse (Plan 4)
- recall_memory_search (Plan 4)

DI 设计:
- pg_session_factory: () -> Session(同步 SQLAlchemy session, 跟 PR #39 / v1.0 一致)
- age_executor: AGEExecutor stub(Plan 1A 已 ship; Plan 2 sync edge 用)
- milvus_client: pymilvus client(Plan 1A 已 ship)
- embed_service: 复用 v0.7 EmbeddingService(qwen v3 1024d)
- llm_extractor: Plan 2 LLMExtractor(本 Plan 不 import / 不调用)
- llm_judge: Plan 2 ConflictJudge(本 Plan 不 import / 不调用)
- injection_classifier: Plan 5 InjectionClassifier(默认 None = no check)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from app.memory.models import (
        ChatMemoryEdge,
        ChatMemoryEpisode,
        ChatMemoryWorkingBlock,
    )

logger = logging.getLogger(__name__)


class HierarchicalMemory:
    """C.5 3-tier hierarchical memory implementation.

    Tier 1 working blocks(persona / scratchpad)+ Tier 2 archival graph + Tier 3 recall.
    """

    def __init__(
        self,
        pg_session_factory: Any,
        age_executor: Any,
        milvus_client: Any,
        embed_service: Any,
        llm_extractor: Any,
        llm_judge: Any,
        injection_classifier: Any | None = None,
    ) -> None:
        self._pg_session_factory = pg_session_factory
        self._age = age_executor
        self._milvus = milvus_client
        self._embed = embed_service
        self._llm_extractor = llm_extractor
        self._llm_judge = llm_judge
        self._injection_classifier = injection_classifier

    # === Tier 1 Working Memory(Plan 1B Task 6 实现) ===

    async def get_working_blocks(self, user_id: UUID) -> dict[str, ChatMemoryWorkingBlock]:
        """Return {block_name: block} for user's persona / scratchpad.

        新用户 / 没建过 block 的用户 → 返回空 dict(不自动建).
        cold_start 走单独 path 给新用户初始化 block.
        """
        from app.memory.models import ChatMemoryWorkingBlock

        session = self._pg_session_factory()
        try:
            rows = (
                session.query(ChatMemoryWorkingBlock)
                .filter(ChatMemoryWorkingBlock.user_id == user_id)
                .all()
            )
            result = {b.block_name: b for b in rows}
            for r in rows:
                session.expunge(r)
            return result
        finally:
            session.close()

    async def core_memory_append(
        self, user_id: UUID, block_name: str, content: str
    ) -> ChatMemoryWorkingBlock:
        """Append content to block. Auto-paging if exceed max_tokens.

        Plan 1B: paged_out_lines 通过 logger.warning 记(后续 Plan 2 ship 后,
        改成调 self.archival_memory_insert 真归档).
        """
        from app.memory.models import ChatMemoryWorkingBlock
        from app.memory.working_blocks import (
            BLOCK_DEFAULTS,
            approx_token_count,
            do_append_with_paging,
        )

        if block_name not in BLOCK_DEFAULTS:
            raise ValueError(
                f"unknown block_name {block_name!r}; valid: {list(BLOCK_DEFAULTS.keys())}"
            )

        session = self._pg_session_factory()
        try:
            block = (
                session.query(ChatMemoryWorkingBlock)
                .filter(
                    ChatMemoryWorkingBlock.user_id == user_id,
                    ChatMemoryWorkingBlock.block_name == block_name,
                )
                .first()
            )
            if block is None:
                block = ChatMemoryWorkingBlock(
                    user_id=user_id,
                    block_name=block_name,
                    content="",
                    token_count=0,
                    max_tokens=BLOCK_DEFAULTS[block_name],
                )
                session.add(block)
                session.flush()

            new_content, paged = do_append_with_paging(
                existing=block.content,
                new=content,
                max_tokens=block.max_tokens,
            )
            block.content = new_content
            block.token_count = approx_token_count(new_content)

            if paged:
                logger.warning(
                    "core_memory_append: paged %d lines from block %s/user=%s — "
                    "Plan 2 ship 后改 archival_memory_insert 真归档(spec § 7)",
                    len(paged),
                    block_name,
                    user_id,
                )

            session.commit()
            session.refresh(block)
            session.expunge(block)
            return block
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    async def core_memory_replace(
        self,
        user_id: UUID,
        block_name: str,
        old_content: str,
        new_content: str,
    ) -> ChatMemoryWorkingBlock:
        """Exact substring replace. Raise ValueError if not found."""
        from app.memory.models import ChatMemoryWorkingBlock
        from app.memory.working_blocks import (
            BLOCK_DEFAULTS,
            approx_token_count,
            do_replace_exact,
        )

        if block_name not in BLOCK_DEFAULTS:
            raise ValueError(
                f"unknown block_name {block_name!r}; valid: {list(BLOCK_DEFAULTS.keys())}"
            )

        session = self._pg_session_factory()
        try:
            block = (
                session.query(ChatMemoryWorkingBlock)
                .filter(
                    ChatMemoryWorkingBlock.user_id == user_id,
                    ChatMemoryWorkingBlock.block_name == block_name,
                )
                .first()
            )
            if block is None:
                raise ValueError(
                    f"core_memory_replace: block {block_name} not found for user {user_id}"
                )

            replaced = do_replace_exact(block.content, old_content, new_content)
            block.content = replaced
            block.token_count = approx_token_count(replaced)
            session.commit()
            session.refresh(block)
            session.expunge(block)
            return block
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # === Tier 2 Archival ===

    async def archival_memory_insert(
        self,
        user_id: UUID,
        content: dict[str, Any],
        reasoning: str,
        importance: float,
        evidence_quote: str,
        episode_id: UUID,
    ) -> ChatMemoryEdge:
        raise NotImplementedError("filled by Plan 2")

    async def archival_memory_search(
        self, user_id: UUID, query: str, k: int = 5
    ) -> list[ChatMemoryEdge]:
        raise NotImplementedError("filled by Plan 3")

    async def archival_memory_traverse(
        self,
        user_id: UUID,
        start_label: str,
        hops: int = 2,
        rel_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError("filled by Plan 4")

    # === Tier 3 Recall ===

    async def recall_memory_search(
        self, user_id: UUID, query: str, k: int = 5
    ) -> list[dict[str, Any]]:
        raise NotImplementedError("filled by Plan 4")

    # === 持久化 episodes(Plan 1B Task 7 实现) ===

    async def write_episode(
        self,
        user_id: UUID,
        session_id: UUID,
        episode_index: int,
        user_message: str,
        agent_response: str,
        source_kind: str = "chat_turn",
    ) -> ChatMemoryEpisode:
        # Task 7 fill
        raise NotImplementedError("filled by Plan 1B Task 7")

    async def get_unextracted_episodes(
        self, user_id: UUID, limit: int = 100
    ) -> list[ChatMemoryEpisode]:
        # Task 7 fill
        raise NotImplementedError("filled by Plan 1B Task 7")

    async def mark_episode_extracted(
        self,
        episode_id: UUID,
        extracted_by: str,
        extraction_metadata: dict[str, Any],
    ) -> None:
        # Task 7 fill
        raise NotImplementedError("filled by Plan 1B Task 7")
