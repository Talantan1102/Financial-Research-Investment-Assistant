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
- embed_cache: Plan 5 EmbedCache(默认 None = 直走 embed_service, 不缓存); 契约 § 9
- prompt_cache_store: Plan 5 PromptCacheStore(默认 None = 不 mark prompt cache); 契约 § 9
"""

from __future__ import annotations

import logging
from datetime import UTC
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from app.memory.persona_service import PersonaService
from app.memory.working_blocks import PERSONA_BLOCK_NAME

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
        embed_cache: Any | None = None,
        prompt_cache_store: Any | None = None,
        persona_service: PersonaService | None = None,
    ) -> None:
        self._pg_session_factory = pg_session_factory
        self._age = age_executor
        self._milvus = milvus_client
        self._embed = embed_service
        self._llm_extractor = llm_extractor
        self._llm_judge = llm_judge
        self._injection_classifier = injection_classifier
        # Plan 5 cost optimization DI hooks (契约 § 9). 默认 None 保 Plan 1B 测试无破坏.
        self._embed_cache = embed_cache
        self._prompt_cache_store = prompt_cache_store
        # Task 17: PersonaService DI — caller may inject mock; defaults to real instance.
        self._persona_service: PersonaService = persona_service or PersonaService(
            pg_session_factory=pg_session_factory
        )

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
    ) -> ChatMemoryWorkingBlock | None:
        """Append content to block. Auto-paging if exceed max_tokens.

        Plan 1B: paged_out_lines 通过 logger.warning 记(后续 Plan 2 ship 后,
        改成调 self.archival_memory_insert 真归档).

        Task 17: persona block routes to PersonaService.apply_agent_append;
        returns None (MCP tool caller handles None for persona path).
        """
        # Task 17: persona block — route to PersonaService, skip legacy path
        # C65: use PERSONA_BLOCK_NAME constant (SSOT in working_blocks.py).
        if block_name == PERSONA_BLOCK_NAME:
            self._persona_service.apply_agent_append(user_id=user_id, content=content)
            return None

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
    ) -> ChatMemoryWorkingBlock | None:
        """Exact substring replace. Raise ValueError if not found.

        Task 17: persona block routes to PersonaService.apply_agent_replace;
        returns None (MCP tool caller handles None for persona path).
        """
        # Task 17: persona block — route to PersonaService, skip legacy path
        # C65: use PERSONA_BLOCK_NAME constant (SSOT in working_blocks.py).
        if block_name == PERSONA_BLOCK_NAME:
            self._persona_service.apply_agent_replace(
                user_id=user_id, old_content=old_content, new_content=new_content
            )
            return None

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
                    age_merge_node(
                        session=session,
                        node_id=cast(UUID, node.node_id),
                        entity_type=entity_type,
                    )
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
            elif self._llm_judge is None:
                # 无裁判 = 不做冲突消解,一律追加(防御性正确 + 元评估写侧消融削弱版)
                verdict = ConflictVerdict(
                    action=ConflictAction.APPEND_NEW,
                    reasoning="no llm_judge (conflict resolution disabled)",
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

            existing_ids: list[UUID] = [cast(UUID, e.edge_id) for e in existing]
            src_node_id = cast(UUID, src_node.node_id)
            tgt_node_id = cast(UUID, tgt_node.node_id)

            # BM25 检索:建边时填 search_tokens(jieba 切词),否则 search_vector 为空、
            # 中文 query 零召回(2026-06-08 对话流评估读侧全红根因之一)
            from app.memory.registry import jieba_tokenize_for_search

            _search_text = " ".join(
                [rel_type, src_label, tgt_label, reasoning or ""]
                + [str(v) for v in properties.values()]
            )
            search_tokens = jieba_tokenize_for_search(_search_text)

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
                search_tokens=search_tokens,
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

            new_edge_id = cast(UUID, new_edge.edge_id)

            # Step 7a: AGE Cypher CREATE 边镜像 — best-effort(2026-06-05 冒烟发现 #5)。
            # 原"failure rolls back PG"的原子语义在无 AGE 扩展的环境(生产
            # industry_assistant 库连可装的 age 都没有)下等于"所有写入永远失败";
            # PG 是 SSOT,镜像失败降级为 warning(与节点镜像、Milvus outbox 同哲学,
            # age_sync 内部已用 SAVEPOINT 保证失败不毒事务)。
            try:
                age_create_edge(
                    session=session,
                    edge_id=new_edge_id,
                    source_node_id=src_node_id,
                    target_node_id=tgt_node_id,
                    rel_type=rel_type,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "AGE edge mirror degraded (best-effort, PG 仍为 SSOT): %s; edge_id=%s",
                    exc,
                    new_edge_id,
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
        """spec § 5 3-way Hybrid + RRF v2.

        路径:
            1. BM25 (PG GIN + jieba) — 词法
            2. Vector (Milvus + qwen embed) — 语义
            (Graph 不进 default, 留 archival_memory_traverse 调用)

        Fusion: rrf.reciprocal_rank_fusion_v2 (importance 三档 + 时间感知).
        Instrumentation: log_retrieval_hit 落库 → Plan 5 calibration / Plan 8 eval 消费.

        失败模式:
            - vector_search 失败(Milvus / embed) → log warning, 仅返 BM25 结果
            - instrumentation 失败 → log warning 不阻塞 search
            - 完全无召回 → 返空 list
        """
        import time

        from sqlalchemy import select

        from app.memory.instrumentation import log_retrieval_hit
        from app.memory.models import ChatMemoryEdge as _Edge
        from app.memory.retriever import (
            bm25_search,
            format_edges_meta_for_rrf,
            vector_search,
        )
        from app.memory.rrf import reciprocal_rank_fusion_v2

        t0 = time.time()
        session = self._pg_session_factory()
        # 生产 SessionLocal 默认 expire_on_commit=True:下面 commit(log_retrieval_hit)
        # 会 expire 已加载边的所有属性,再 expunge 返回的就是失效+detached 对象,
        # 调用方一访问列属性就 DetachedInstanceError。置 False 保证 commit 后列值留存,
        # expunge 后边可脱离 session 安全读(读路径不依赖会话内对象新鲜度)。
        session.expire_on_commit = False
        try:
            # 路径 1: BM25 (sync)
            bm25_hits: list[dict[str, Any]] = []
            try:
                bm25_hits = bm25_search(session, user_id=user_id, query=query, k=k * 2)
            except Exception as exc:  # noqa: BLE001
                logger.warning("archival_memory_search BM25 failed: %s", exc)

            # 路径 2: Vector (async)
            vector_hits: list[dict[str, Any]] = []
            if self._milvus is not None and self._embed is not None:
                try:
                    vector_hits = await vector_search(
                        session,
                        milvus_client=self._milvus,
                        embed_service=self._embed,
                        user_id=user_id,
                        query=query,
                        k=k * 2,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("archival_memory_search vector failed: %s", exc)

            edges_meta = format_edges_meta_for_rrf([bm25_hits, vector_hits])
            if not edges_meta:
                return []

            rrf_top = reciprocal_rank_fusion_v2(
                retriever_results=[bm25_hits, vector_hits],
                edges_meta=edges_meta,
                top=k,
            )
            if not rrf_top:
                return []

            top_eids = [r["edge_id"] for r in rrf_top]
            edges = (
                session.execute(
                    select(_Edge).where(
                        _Edge.edge_id.in_(top_eids),
                        _Edge.invalidated_at.is_(None),
                    )
                )
                .scalars()
                .all()
            )
            by_id = {str(e.edge_id): e for e in edges}
            ordered: list[ChatMemoryEdge] = []
            for r in rrf_top:
                edge = by_id.get(r["edge_id"])
                if edge is not None:
                    ordered.append(edge)

            latency_ms = int((time.time() - t0) * 1000)
            try:
                log_retrieval_hit(
                    session,
                    user_id=user_id,
                    query_text=query,
                    retrieved_edge_ids=[r["edge_id"] for r in rrf_top],
                    rrf_scores={r["edge_id"]: r["score"] for r in rrf_top},
                    edges_meta=edges_meta,
                    retriever_breakdown={
                        "bm25": len(bm25_hits),
                        "vector": len(vector_hits),
                        "graph": 0,
                    },
                    latency_ms=latency_ms,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("log_retrieval_hit failed: %s", exc)

            session.commit()
            for e in ordered:
                session.expunge(e)
            return ordered
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    async def archival_memory_traverse(
        self,
        user_id: UUID,
        start_label: str,
        hops: int = 2,
        rel_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """spec § 5 路径 3 — on-demand AGE Cypher multi-hop traversal.

        Plan 4 fill (Plan 1 left this as stub raise NotImplementedError).
        Wraps app.memory.retriever.graph_traverse; AGE 不可用时返空 list 不报错
        (符合 spec § 5 graph 路径 fail-safe 语义).
        """
        from app.memory.retriever import graph_traverse

        session = self._pg_session_factory()
        try:
            return await graph_traverse(
                session,
                age_executor=self._age,
                user_id=user_id,
                start_label=start_label,
                hops=hops,
                rel_types=rel_types,
            )
        finally:
            session.close()

    # === Tier 3 Recall (Plan 4 fill) ===

    async def recall_memory_search(
        self, user_id: UUID, query: str, k: int = 5
    ) -> list[dict[str, Any]]:
        """spec § 6 Tier 3 — semantic search over PR #39 chat_messages.

        In-memory cosine over qwen-embedded user messages (cap 5000 / user).
        """
        from app.memory.recall_search import RecallSearcher

        if not hasattr(self, "_recall_searcher"):
            self._recall_searcher = RecallSearcher(
                session_factory=self._pg_session_factory,
                embed_service=self._embed,
            )
        return await self._recall_searcher.search(user_id, query, k)

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
