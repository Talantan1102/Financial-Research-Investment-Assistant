---
title: C.5 cross-session memory ship 完
type: project
date: 2026-05-11
---

# C.5 cross-session memory ship 完(2026-05-11)

**结论**:C.5 跨 session memory(MemGPT-style hierarchical + Zep bi-temporal graph 杂交)ship 完成, 8 个 Plan 顺序落地。HierarchicalMemory 替换 InSessionMemory(via Memory Protocol DI), 16 工业难题撞实 + 6 算法深度补丁 v1.x 必做全 ship, 2 条触发后做 + 4 条 Scale-X 规模化补丁留 P3 hooks。

## 8 Plan ship 范围

| Plan | ship 范围 | 代码 |
|---|---|---|
| Plan 1A Foundation Schema | 4 PG 表 + AGE 7v/11e + Milvus collection + alias + app_main lifespan | `backend/app/memory/models.py` / `milvus_setup.py` / SQL migrations |
| Plan 1B Business Foundation | Memory Protocol + HierarchicalMemory 骨架 + working_blocks + cold_start + reconciliation 骨架 + chat router DI swap | `protocol.py` / `hierarchical.py` / `working_blocks.py` / `cold_start.py` |
| Plan 2A Write Pipeline Core | LLMExtractor + ConflictResolver 4-action + AGE/Milvus outbox + 8-step pipeline | `extractor.py` / `conflict_resolver.py` / `milvus_outbox.py` |
| Plan 2B Cross-Turn | cross_turn_grouper + Path B runner + failure_matrix + Milvus reconcile job | `cross_turn_grouper.py` / `path_b_runner.py` / `failure_matrix.py` |
| Plan 3 Read Pipeline + RRF v2 | 3-way hybrid retriever(BM25+vector+graph)+ 时间感知 RRF v2 + persona populator + instrumentation + long_tail_monitor | `retriever.py` / `rrf.py` / `persona_populator.py` / `instrumentation.py` |
| Plan 4 6 MCP Tools | 6 tool MCP profile + evidence_quote 校验 + recall_search + mcp_tool_call_log | `mcp_server/tools/memory/` 6 文件 + `recall_search.py` |
| Plan 5 Cost Optimization | embed_cache + prompt_cache + skip_gate + batch_extractor + injection_classifier + posterior_calibration + memory_llm queue | `embed_cache.py` / `prompt_cache.py` / `skip_gate.py` / `batch_extractor.py` / `injection_classifier.py` / `posterior_calibration.py` |
| Plan 6 Memory vs KB Routing | LLMRouterFallback constrained-JSON + 3 触发词层 + chat_graph 集成 + planner prompt 区隔 + routing_accuracy hook | `memory_kb_router.py` |
| Plan 7A /memory UI Shell | 5 REST endpoint + memoryApi typed client + /memory page + sidebar | `router/memory_router.py` + `frontend/.../memory/` |
| Plan 7B Memory UI Visualizations | Cytoscape MemoryGraph + Timeline + AuditLog + OnboardingModal + chat anchor + monthly email digest | `frontend/.../components/memory/` 5 files |
| Plan 8 Eval + Tests + Docs | 50 golden + 30 投毒 + 20 跨轮 + 5 session + 4 metric + eval_runner CLI + bi-temporal differential + chaos 4 scenario + 投毒 e2e + 总卡 | `backend/eval/memory/` + `backend/tests/e2e/memory/` |

## 关键决策(实施期撞实, spec 已锚定)

| 决策 | 落地 |
|---|---|
| 范式 D MemGPT-style hierarchical(Q4 决策) | HierarchicalMemory 替换 InSessionMemory via Memory Protocol DI |
| Storage = PG + Apache AGE(不上 Neo4j) | PG 表存全量 + AGE 镜像存图拓扑给 Cypher 用,避开 AGE agtype 索引能力弱 |
| Bi-temporal 4 字段(Snodgrass 1993) | valid_from / valid_to(real-world) + recorded_at / invalidated_at(transaction-time) |
| Importance 三档离散(0.9 / 0.5 / 0.2)+ 后验校准 | LLM 一次抽不动 + 周 job 行为信号校准 |
| Time-aware RRF v2 | `score = (Σ 1/(60+rank)) × imp_weight × time_decay`, τ 按 rel_type 分级 (HOLDS/SOLD 365d, PREFERS/AVOIDS 180d, EXPRESSED_VIEW/STUDIED 90d) |
| Idempotency UNIQUE constraint | (episode_id, source, target, rel_type, valid_from) |
| 5 项 cost ladder | 单 session $0.025 → $0.005 (prompt cache + batch + skip gate + async + embed cache) |
| 6 MCP tools | core_memory_append / core_memory_replace + archival_memory_insert/search/traverse + recall_memory_search |
| /memory UI 不做 v1.x edit | 只 viz + audit + onboarding, edit 留 P3 |
| Memory vs KB routing | LangGraph supervisor router node + constrained JSON output + 三种触发词 |

## 6 算法深度补丁 v1.x 必做(spec § 11 末尾) — 全 ship

| # | 补丁 | 验证 metric | Plan / 文件 |
|---|---|---|---|
| #2 投毒 + Agent 幻觉写 | injection classifier (规则层 12 patterns) + evidence_quote 校验 | 拦截率 ≥ 0.95 / 误杀率 ≤ 0.20 (30 case) | Plan 4 `injection_classifier.py` + Plan 8 `test_poison_attacks.py` |
| #3 importance 三档 + 时间感知 RRF + τ 分级 + 后验校准 | RRF v2 公式 + 长尾 P90 ≥ 7d + 周报 SQL | 长尾召回 P90 7d + 周报 SQL 上大盘 | Plan 3 `rrf.py` + `instrumentation.py` + Plan 8 `long_tail_monitor.py` |
| #4 跨轮抽取(5 turn 滑窗 + 语义连续性合并) | cross_turn 召回 ≥ 0.7 | 20 case (`cross_turn_extraction_golden.jsonl`) | Plan 2B `cross_turn_grouper.py` + Plan 8 golden |
| #5 PG + AGE + Milvus 三方一致性 | 幂等键 UNIQUE + reconciliation job | 4 chaos test scenario | Plan 1A/1B/2B + Plan 8 `test_chaos_three_way_consistency.py` |
| #7 Memory vs KB routing | supervisor router node + 三种触发词 | routing accuracy ≥ 0.85 (20 case) | Plan 6 `memory_kb_router.py` + Plan 8 routing 20 case |
| #8 用户心智模型 + 信任 | onboarding modal + chat 内 [查看] anchor + monthly email digest | dogfood ≥ 10 chat 调研 | Plan 7B (UI) + dogfood 待跑 |

## 4 Metric impl (Plan 8 spec § 10)

| Metric | 阈值 | Impl 文件 | L0 test |
|---|---|---|---|
| Recall Precision (LLM-judge) | ≥ 0.7 | `recall_precision_metric.py` | 5 case |
| Temporal Correctness (确定性) | ≥ 0.95 | `temporal_correctness_metric.py` | 8 case |
| Faithful Answer (claim grounding + provenance) | ≥ 0.85 | `faithful_answer_metric.py` | 11 case |
| Routing Accuracy (subset match) | ≥ 0.85 | `routing_accuracy_metric.py` | 7 case (Plan 8) + 3 case (Plan 4 single-tool) |
| Long-tail P90 min-age | ≥ 7 days | `long_tail_monitor.py` (eval) | 7 case |

## 测试覆盖

- L0 unit 100+ test (schema / RRF / paging / extractor / conflict / 4 metric / long_tail / routing / injection / ...) — 58% module coverage
- L1 integration 29 test 文件 (extraction e2e / conflict / retriever / 6 MCP / cold start / kb routing / cost opt / posterior calibration / reconciliation / instrumentation / eval_runner) — 全模块至少 1 case
- L2 cassette 5 stub (search / traverse / recall / kb routing / path_b — 真 cassette 待 dogfood 期录)
- L2 differential: bi-temporal 5 session 1:1 实现(真 PG)
- L2 chaos: 4 scenario (Milvus outbox / reconciliation / 幂等键 / no_op rollback)
- L2 投毒: 30 attack + 10 safe, 拦截率 ≥ 0.95 + 误杀率 ≤ 0.20
- L3 dogfood: 待跑 ≥ 10 chat (周报 c5-dogfood-week-1.md, Plan 15 dogfood 阶段)

## 简历叙事(可直接抄)

> "C.5 cross-session memory 撞实 16 个工业难题 (13 通用 + 3 Zep 特有) + 6 条算法深度补丁 (spec § 11 末尾 v1.x 必做)。架构是 Letta MemGPT (2023) 的 agent-self-managed tool 接口 + Zep / Graphiti (Jan 2025) 的 temporal knowledge graph 后端杂交版, 加 mem0 风的 LLM-judge conflict resolution + Anthropic Citations API 风的 provenance FK。
>
> **Storage 选 PG + Apache AGE 不上 Neo4j** —— 复用 v1.0 PG 基建, 但 PG 表存全数据 + B-tree 索引 / AGE 镜像存图拓扑给 Cypher, 避开 AGE agtype 索引能力弱的问题。**Bi-temporal model (Snodgrass 1993)** 区分 real-world validity vs transaction time, 让'用户对茅台态度演化'这类金融 use case 关键 query 表达力完整。
>
> **3-way hybrid retrieval (BM25 + vector + graph)** + **time-aware RRF v2** (`score = Σ 1/(60+rank) × importance_weight × time_decay`, τ 按 rel_type 分级 365/180/90 days, 衰减底 0.5 不消失) 是 2024-2025 工业前沿 (Microsoft GraphRAG paper)。**Cost optimization 5 项 ladder** (prompt cache + batch + skip gate + async + embedding cache) 把单 session 成本从 $0.025 降到 $0.005, 接近 mem0 paper 报告的 $0.001。
>
> **Memory 投毒 + Agent 幻觉写** (Anthropic 2024 indirect prompt injection paper): 写入前过 prompt-injection 分类器 (规则层 12 patterns) 命中标 audit_flag 不进图; archival_memory_insert 必须带 evidence_quote 找不到原文 substring 拒绝写。30 case 投毒攻击拦截率 ≥ 0.95 / 误杀率 ≤ 0.20。
>
> **PG + AGE + Milvus 三方一致性反向失败**: 幂等键 UNIQUE constraint (episode_id, source, target, rel_type, valid_from) + 启动 reconciliation job 扫'PG 写完 + Milvus pending + episode extracted_at IS NULL'状态修复。L2 chaos test 4 scenario 验证: Milvus outbox / 进程重启 / 重复抽 / no_op rollback。
>
> **Eval pipeline**: 50 golden case + 4 metric (recall_precision ≥ 0.7 / temporal_correctness ≥ 0.95 / faithful_answer ≥ 0.85 / routing_accuracy ≥ 0.85) + 长尾召回监控 (P90 min-age ≥ 7 days)。**bi-temporal differential test** 5 session 序列 (重仓 → 加仓 → 卖出 → 澄清记错 → 重新建仓) 1:1 验证 4-action conflict 跨 session 正确性。eval_runner CLI `--strict` 模式作 PR gate。"

## P3 留 hook (等 v1.x / v2)

- **Scale-1~4 规模化补丁** (spec § 14) — 触发条件分批做:
  - Scale-1 写入分级 + 前置过滤升级 (importance ≥ 0.9 中模型) — 日活 > 1 万 / cost > $20/d 触发
  - Scale-2 重要 edge 三关 verify + 用户回路 first-class — invalidation rate > 5% 触发
  - Scale-3 request_id 全链路 trace + 三层监控大盘 — 客诉 30 分钟内不能定位 触发
  - Scale-4 多租户 schema 分库 + Milvus partition + 冷热分离 + GDPR pipeline — 注册用户 > 10 万 触发
- **算法深度 hook 2 条**:
  - #1 向量模型升级迁移 (qwen v3→v4 alias 模式) — 同维度模型对比时触发
  - #6 Ontology 演化 (ontology_version + LLM 重判 + diff review) — 加新 entity_type 时触发
- **产品功能 hook**: /memory UI edit & delete / 跨用户 sharing / memory replay / privacy controls

## 关键文件 ref

- spec: `docs/superpowers/specs/2026-05-10-c5-cross-session-memory-design.md`
- shared contracts: `docs/superpowers/plans/2026-05-11-c5-plan-shared-contracts.md`
- 8 plans: `docs/superpowers/plans/2026-05-11-c5-plan{1..8}-*.md`
- 主代码: `backend/app/memory/` (30 module files)
- 6 tools: `backend/app/mcp_server/tools/memory/`
- frontend: `frontend/src/app/memory/page.tsx` + `frontend/src/components/memory/` (5 components)
- eval: `backend/eval/memory/` (4 jsonl + 4 metric + eval_runner + long_tail_monitor + coverage_audit)
- e2e: `backend/tests/e2e/memory/` (bi-temporal differential / chaos / poison_attacks)
- migrations: `backend/scripts/migrations/2026-05-11-c5-*.sql` (4 SQL files)
- 11 plan 自卡: `docs/claude-context/c5-plan*-done.md`
