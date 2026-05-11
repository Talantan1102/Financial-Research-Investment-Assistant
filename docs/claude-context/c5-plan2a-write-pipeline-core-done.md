---
name: c5-plan2a-write-pipeline-core-done
description: C.5 Plan 2A Write Pipeline Core (Path A) ship — Step 1-7 完整 + bi-temporal 正确性 + AGE/Milvus 三方一致性
type: project
---

C.5 Plan 2A (Write Pipeline Core, Path A 主体) ship — 2026-05-11.

## ship 范围

- `app.memory.extractor` LLMExtractor + Pydantic 强 schema (importance 三档 + 11 rel_type whitelist + 7 entity_type whitelist)
- `app.memory.conflict_resolver` ConflictResolver 4-action LLM-judge + fail-safe APPEND_NEW + apply_action (bi-temporal 4 字段正确性)
- `app.memory.age_sync` age_create_edge + age_merge_node thin wrapper (PG 同事务 Cypher CREATE / MERGE)
- `app.memory.milvus_outbox` build_edge_embed_text + enqueue_milvus_insert + try_milvus_insert (try inline + fallthrough enqueue, 失败不 rollback PG)
- `app.memory.hierarchical.archival_memory_insert` 完整 8-step Path A pipeline (替换 Plan 1B stub)
- pending_milvus_inserts SQL migration (UNIQUE edge_id, ON CONFLICT DO UPDATE, partial index for active retries)
- 测试覆盖: L0 extractor (6) + conflict_resolver (7) + age_sync (3) + milvus_outbox (3); L1 apply_action (4) + extractor_e2e (4) + conflict_resolver_e2e (3) + milvus_outbox_e2e (5) + write_pipeline_hardening (2)

## 关键决策(实施期撞实)

- **valid_to vs invalidated_at 严格分离**: spec § 2 行 247 categorical, 区分"事实演化(用户卖了)"vs"系统记错(用户澄清)", 金融审计场景必要; apply_action 用两条独立 update stmt 各自填一字段
- **Milvus 走 outbox 不进 PG 事务**: PG/AGE 同事务保 source-of-truth 原子, Milvus eventual consistent (Plan 2B Celery reconcile); try_milvus_insert 把异常吞掉 → enqueue 写 outbox 表 → return False, 不抛
- **fail-safe APPEND_NEW**: ConflictResolver LLM 失败 / 返回非法 action → 默认 APPEND_NEW (保守, 不丢信息), 优于 raise 中断 chat
- **importance 三档双层防御**: Pydantic field_validator (写入路径 reject) + PG CHECK constraint (storage layer 兜底), 给 Plan 3 RRF v2 三档映射打基础
- **sync session 严守 Plan 1B 契约**: HierarchicalMemory pg_session_factory 是 sync callable, 整个 archival_memory_insert pipeline 内用 sync `session.query()` / `session.execute(stmt)` / `session.commit()` 路径; 不 retrofit async path (跟 Plan 1B + PR #39 / v1.0 一致)
- **AGE node MERGE best-effort**: get_or_create_node 在 INSERT chat_memory_nodes 后调 age_merge_node, 失败 logger.debug 不抛 — Plan 1B 没承诺 PG/AGE node 同事务一致, Plan 2A 补 best-effort, edge MERGE 时若节点缺失 Cypher MATCH 会失败 → 整事务 rollback
- **AGE edge CREATE 失败整事务 rollback**: edge 是 source-of-truth 一部分, AGE Cypher 失败应整事务 rollback 让上层 retry, 跟 spec § 4 失败处理矩阵一致
- **Path A 跳过 LLM extraction**: Path A caller (Plan 4 MCP tool) 已传半结构化 content dict (rel_type/src_label/tgt_label/valid_from/...), 直接走 Step 3-8; LLMExtractor 留给 Path B (Plan 2B end-of-session batch) 调用
- **monkeypatch age_*_in_test_environments**: 本地 postgres:15 镜像无 AGE 扩展, L1 e2e test 通过 monkeypatch age_create_edge / age_merge_node 为 no-op 让 PG 主事务走通; AGE 同事务行为单独由 hardening test (test_age_failure_rolls_back_pg) 验

## 跟 spec / 共享契约对齐

- spec § 4 Step 1 (write_episode 复用 Plan 1B) ✓
- spec § 4 Step 2 (LLM Extraction Path A 半结构化跳过 + Pydantic schema) ✓
- spec § 4 Step 3 (Entity Normalization + audit_flag 写 properties._normalize_audit) ✓
- spec § 4 Step 4 (Existing edges current snapshot 5 latest, invalidated_at IS NULL) ✓
- spec § 4 Step 5 (4-action LLM-judge + fail-safe APPEND_NEW) ✓
- spec § 4 Step 6 (Apply Action bi-temporal valid_to vs invalidated_at 分离) ✓
- spec § 4 Step 7 (AGE 同事务 Cypher CREATE + Milvus outbox INSERT) ✓
- spec § 4 Step 8 (mark_episode_extracted, extracted_by='agent', metadata 含 edge_count/action/rel_type/importance) ✓
- spec § 11 算法深度补丁 #3 importance 三档 (Pydantic + PG CHECK 双层防御) ✓
- spec § 11 算法深度补丁 #5 三方一致性 (PG 主事务 + outbox 兜底; Plan 2B reconciliation Celery job 收) — 主事务正确性已 ship, reconcile 推 Plan 2B
- 共享契约 § 17 A2 (4) LLMExtractor 双方法: extract (Plan 2A 实现) / extract_facts (Plan 2B) ✓
- 共享契约 § 17 A2 (5) 类型统一 ExtractionOutput + ExtractedEdge / ExtractedEntity, 不用 ExtractedFact ✓

## 偏离 plan 文件 (按 contracts § 17 audit resolutions)

- Plan 文件用 async session pattern (`async with pg_memory_fixture() as session`), 实际 Plan 1B ship 的是 sync callable factory (`pg_memory_session_factory()`) — 实施时严守 Plan 1B 契约, 测试 + 实现都用 sync session
- Plan 文件 ConflictAction 用 `from enum import StrEnum`(plan 中误为 `from enum import StrEnum` — 实际写 `class ConflictAction(str, Enum)` 撞 ruff UP042, 改为 `class ConflictAction(StrEnum)` 满足 lint)
- Plan 文件 apply_action `async def`, 实际改 `def` (sync) 因为 Plan 1B Session 是 sync; archival_memory_insert 整体仍是 async (DI Protocol 要求), 内部对 sync session 直接调
- Plan 文件 _get_or_create_node 内嵌 AGE Cypher MERGE 用 raw f-string, 提取到 age_sync.age_merge_node 集中防御 entity_type 白名单 (Plan 5 inject classifier 之前的最小防御)
- 加了 ExtractedEntity entity_type validator (plan 文件没显式提, 但 spec § 3 Ontology 要求 7 类白名单)

## 已知 follow-up (Plan 2B / Plan 4 / Plan 5 收)

- Path B end-of-session 兜底批 + idle-30min 触发 + 跨轮抽取 (#4 算法深度补丁) → Plan 2B
- Celery `pending_milvus_inserts` retry job (5min 周期, task name `reconcile_pending_milvus`) + 失败处理矩阵完整 → Plan 2B
- prompt cache / batch / skip-extraction gate / async via Celery / embedding cache → Plan 5
- evidence_quote 校验 (是否真在 episode 原文出现) → Plan 4 在 archival_memory_insert MCP wrapper 层 + Plan 5 InjectionClassifier
- archival_memory_insert MCP tool (Plan 4 ship) — 调用本 plan 的 HierarchicalMemory.archival_memory_insert, 上层加 evidence_quote 校验 + injection 检查
- Path B LLMExtractor.extract_facts (5-turn 滑动窗口, contracts § 17 A2 (4)) — Plan 2B

## 关键文件 ref

- `backend/app/memory/extractor.py` — LLMExtractor + ExtractedEntity / ExtractedEdge / ExtractionOutput Pydantic schemas
- `backend/app/memory/conflict_resolver.py` — ConflictAction StrEnum + ConflictResolver judge + apply_action
- `backend/app/memory/age_sync.py` — age_create_edge + age_merge_node Cypher CREATE / MERGE thin wrappers
- `backend/app/memory/milvus_outbox.py` — build_edge_embed_text + enqueue_milvus_insert + try_milvus_insert
- `backend/app/memory/hierarchical.py` — archival_memory_insert 8-step pipeline (Plan 1B stub 替换)
- `backend/scripts/migrations/2026-05-11-c5-pending-milvus-outbox.sql` — outbox table
- `backend/tests/unit/memory/test_extractor.py` (6) / `test_conflict_resolver.py` (7) / `test_age_sync.py` (3) / `test_milvus_outbox.py` (3)
- `backend/tests/integration/memory/test_apply_action_e2e.py` (4) / `test_extractor_e2e.py` (4) / `test_conflict_resolver_e2e.py` (3) / `test_milvus_outbox_e2e.py` (5) / `test_write_pipeline_hardening.py` (2)

## 简历可讲点

- "PG 主事务包 [INSERT chat_memory_edges + AGE Cypher CREATE] 保拓扑+数据原子性, Milvus 走 outbox eventual consistent, 解 3 系统(PG/AGE/Milvus)写入一致性 — 算法深度补丁 #5 三方一致性主体"
- "bi-temporal 4 字段(valid_from/to/recorded_at/invalidated_at)严格分离 categorical, 区分'事实演化'(update_validity)与'系统记录纠错'(contradict_existing), 解金融审计 + GDPR 删除证据保留"
- "ConflictResolver fail-safe APPEND_NEW: LLM 失败 / 返回非法 action → 不抛中断 chat, 保守 INSERT 新 fact (不丢信息), 后续 audit log + posterior calibration 校正; 跟 Letta safety-first / Zep 演化 friendly 兼容"
- "importance 三档双层防御: Pydantic 写入路径 reject + PG CHECK constraint storage 兜底, RRF v2 三档映射(0.95/0.75/0.6)消除 importance 信号噪声"
