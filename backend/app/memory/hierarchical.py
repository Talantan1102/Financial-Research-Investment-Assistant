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
from datetime import UTC
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
    ) -> ChatMemoryEdge | None:
        """spec § 4 Path A — agent-triggered Step 1-8 pipeline.

        Path A 假设 caller (Plan 4 MCP tool) 已给半结构化:
            content = {
                "rel_type": str,
                "source_entity_type": str, "source_label": str,
                "target_entity_type": str, "target_label": str,
                "valid_from": datetime, "valid_to": datetime | None,
                "properties": dict,
            }

        跳过 Step 2 (LLM extraction), 走 Step 3-8.

        Step 3: Entity normalize (registry.normalize_entity, 失败 audit_flag 写)
        Step 4: existing edges query (current snapshot, 5 latest)
        Step 5: ConflictResolver.judge (跳过 if no existing)
        Step 6: apply_action (bi-temporal correctness)
        Step 7: AGE Cypher CREATE (same txn) + Milvus outbox (separate try)
        Step 8: mark_episode_extracted (extracted_by='agent')

        evidence_quote 校验 — Plan 4 archival_memory_insert MCP wrapper 层做.

        Returns the new edge, or None for NO_OP (spec § 4 Step 5 重复事实).
        """
        from sqlalchemy import select

        from app.memory.age_sync import age_create_edge, age_merge_node
        from app.memory.conflict_resolver import (
            ConflictAction,
            ConflictVerdict,
            apply_action,
        )
        from app.memory.milvus_outbox import build_edge_embed_text, try_milvus_insert
        from app.memory.models import ChatMemoryEdge, ChatMemoryNode
        from app.memory.registry import normalize_entity

        rel_type = content["rel_type"]
        src_type = content["source_entity_type"]
        src_label_raw = content["source_label"]
        tgt_type = content["target_entity_type"]
        tgt_label_raw = content["target_label"]
        valid_from = content["valid_from"]
        valid_to = content.get("valid_to")
        properties = dict(content.get("properties", {}))

        # Step 3: Normalize
        src_label, src_audit = normalize_entity(src_type, src_label_raw)
        tgt_label, tgt_audit = normalize_entity(tgt_type, tgt_label_raw)
        if src_audit or tgt_audit:
            properties = {
                **properties,
                "_normalize_audit": {
                    "source": src_audit,
                    "target": tgt_audit,
                    "raw_source": src_label_raw,
                    "raw_target": tgt_label_raw,
                },
            }

        session = self._pg_session_factory()
        try:
            # Step 3.1: get_or_create entity nodes
            def _get_or_create_node(entity_type: str, label: str) -> ChatMemoryNode:
                row = (
                    session.query(ChatMemoryNode)
                    .filter(
                        ChatMemoryNode.user_id == user_id,
                        ChatMemoryNode.entity_type == entity_type,
                        ChatMemoryNode.entity_label == label,
                    )
                    .first()
                )
                if row is not None:
                    return row
                node = ChatMemoryNode(user_id=user_id, entity_type=entity_type, entity_label=label)
                session.add(node)
                session.flush()
                # AGE MERGE node mirror — best-effort (AGE 不可用时静默)
                try:
                    age_merge_node(session=session, node_id=node.node_id, entity_type=entity_type)
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "AGE merge_node failed (best-effort): %s; entity_type=%s",
                        exc,
                        entity_type,
                    )
                return node

            src_node = _get_or_create_node(src_type, src_label)
            tgt_node = _get_or_create_node(tgt_type, tgt_label)

            # Step 4: query existing edges (current snapshot — invalidated_at IS NULL)
            existing = (
                session.execute(
                    select(ChatMemoryEdge)
                    .where(
                        ChatMemoryEdge.user_id == user_id,
                        ChatMemoryEdge.source_node_id == src_node.node_id,
                        ChatMemoryEdge.rel_type == rel_type,
                        ChatMemoryEdge.target_node_id == tgt_node.node_id,
                        ChatMemoryEdge.invalidated_at.is_(None),
                    )
                    .order_by(ChatMemoryEdge.valid_from.desc())
                    .limit(5)
                )
                .scalars()
                .all()
            )

            # Step 5: judge (skip LLM if no existing — APPEND_NEW shortcut)
            if not existing:
                verdict = ConflictVerdict(
                    action=ConflictAction.APPEND_NEW,
                    reasoning="no existing edge",
                )
            else:
                new_summary = (
                    f"{rel_type} {src_type} {src_label} → "
                    f"{tgt_type} {tgt_label} valid_from={valid_from.isoformat()}"
                )
                existing_summaries = [
                    f"{rel_type} {src_type} {src_label} → {tgt_type} {tgt_label} "
                    f"valid_from={e.valid_from.isoformat()} "
                    f"valid_to={e.valid_to.isoformat() if e.valid_to else 'ongoing'}"
                    for e in existing
                ]
                verdict = await self._llm_judge.judge(
                    new_edge_summary=new_summary,
                    existing_edges_summary=existing_summaries,
                )

            existing_ids = [e.edge_id for e in existing]
            src_node_id = src_node.node_id
            tgt_node_id = tgt_node.node_id

            # Step 6: apply
            new_edge = apply_action(
                session=session,
                verdict=verdict,
                existing_edge_ids=existing_ids,
                user_id=user_id,
                source_node_id=src_node_id,
                target_node_id=tgt_node_id,
                rel_type=rel_type,
                valid_from=valid_from,
                valid_to=valid_to,
                source_episode_id=episode_id,
                importance=importance,
                reasoning=reasoning,
                properties=properties,
            )

            if new_edge is None:
                # NO_OP: still mark episode extracted (Step 8)
                self._mark_episode_extracted_in_session(
                    session=session,
                    episode_id=episode_id,
                    extracted_by="agent",
                    extraction_metadata={
                        "edge_count": 0,
                        "action": verdict.action.value,
                        "reasoning": verdict.reasoning,
                    },
                )
                session.commit()
                return None

            new_edge_id = new_edge.edge_id

            # Step 7a: AGE same-txn Cypher CREATE — failure rolls back PG (spec § 4 失败矩阵)
            age_create_edge(
                session=session,
                edge_id=new_edge_id,
                source_node_id=src_node_id,
                target_node_id=tgt_node_id,
                rel_type=rel_type,
            )

            # Step 7b: Milvus outbox (separate semantics — failure absorbed via outbox)
            edge_text = build_edge_embed_text(
                rel_type=rel_type,
                source_entity_type=src_type,
                source_label=src_label,
                target_entity_type=tgt_type,
                target_label=tgt_label,
                reasoning=reasoning,
                properties=properties,
            )
            await try_milvus_insert(
                session=session,
                milvus_client=self._milvus,
                embed_service=self._embed,
                edge=new_edge,
                edge_text=edge_text,
            )

            # Step 8: mark episode extracted
            self._mark_episode_extracted_in_session(
                session=session,
                episode_id=episode_id,
                extracted_by="agent",
                extraction_metadata={
                    "edge_count": 1,
                    "action": verdict.action.value,
                    "rel_type": rel_type,
                    "importance": importance,
                },
            )

            session.commit()
            session.refresh(new_edge)
            session.expunge(new_edge)
            return new_edge
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @staticmethod
    def _mark_episode_extracted_in_session(
        *,
        session: Any,
        episode_id: UUID,
        extracted_by: str,
        extraction_metadata: dict[str, Any],
    ) -> None:
        """Helper: 在已存在 transaction 内标记 episode extracted (不 commit)."""
        from datetime import datetime

        from app.memory.models import ChatMemoryEpisode

        ep = session.query(ChatMemoryEpisode).filter_by(episode_id=episode_id).first()
        if ep is None:
            raise ValueError(f"episode {episode_id} not found")
        ep.extracted_at = datetime.now(UTC)
        ep.extracted_by = extracted_by
        ep.extraction_metadata = extraction_metadata

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
        """Path A 写入 step 1: episode 入库, extracted_at=NULL."""
        from app.memory.models import ChatMemoryEpisode

        session = self._pg_session_factory()
        try:
            ep = ChatMemoryEpisode(
                user_id=user_id,
                session_id=session_id,
                episode_index=episode_index,
                user_message_text=user_message,
                agent_response_text=agent_response,
                source_kind=source_kind,
            )
            session.add(ep)
            session.commit()
            session.refresh(ep)
            session.expunge(ep)
            return ep
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    async def get_unextracted_episodes(
        self, user_id: UUID, limit: int = 100
    ) -> list[ChatMemoryEpisode]:
        """Path B end-of-session batch 用. extracted_at IS NULL 过滤."""
        from app.memory.models import ChatMemoryEpisode

        session = self._pg_session_factory()
        try:
            rows = (
                session.query(ChatMemoryEpisode)
                .filter(
                    ChatMemoryEpisode.user_id == user_id,
                    ChatMemoryEpisode.extracted_at.is_(None),
                )
                .order_by(ChatMemoryEpisode.created_at)
                .limit(limit)
                .all()
            )
            # detach 让 caller 在 session 关后仍可读 attributes
            for r in rows:
                session.expunge(r)
            return rows
        finally:
            session.close()

    async def mark_episode_extracted(
        self,
        episode_id: UUID,
        extracted_by: str,
        extraction_metadata: dict[str, Any],
    ) -> None:
        """Step 8: 抽取完成标记."""
        from datetime import datetime

        from app.memory.models import ChatMemoryEpisode

        session = self._pg_session_factory()
        try:
            ep = session.query(ChatMemoryEpisode).filter_by(episode_id=episode_id).first()
            if ep is None:
                raise ValueError(f"episode {episode_id} not found")
            ep.extracted_at = datetime.now(UTC)
            ep.extracted_by = extracted_by
            ep.extraction_metadata = extraction_metadata
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
