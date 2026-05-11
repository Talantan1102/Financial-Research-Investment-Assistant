---
name: c5-plan1b-business-foundation-done
description: C.5 Plan 1B Business Foundation ship — Memory Protocol + HierarchicalMemory 骨架 + working blocks + cold start + reconciliation
type: project
---

C.5 Plan 1B(Business Foundation)ship — 2026-05-10.

## ship 范围
- `app.memory.protocol` Memory Protocol 完整 9 method 签名(契约 § 2)
- `app.memory.hierarchical` HierarchicalMemory class 骨架 + Plan 1B 范围方法实现(working blocks + episodes 持久化), Plan 2-4 留 stub raise NotImplementedError
- `app.memory.registry` 7+11 ontology + normalize_entity(Stock ts_code / Metric / Strategy 白名单)+ jieba_tokenize_for_search
- `app.memory.working_blocks` Tier 1 CRUD 纯函数(append/replace/auto-paging) + HierarchicalMemory 方法(real PG)
- `app.memory.cold_start` 静态 3 路 seed(持仓 → HOLDS edges 主路径 / preferences / watchlist 留 hook)+ CLI `python -m app.memory.cold_start --user-id X`
- `app.memory.reconciliation` scan_inconsistent_state 入口骨架(算法深度补丁 #5 ship 入口, Plan 5 收束 retry)
- DI 替换: `app.router.chat._build_graph_singleton` 注入 HierarchicalMemory(env DATABASE_URL fallback InSessionMemory 保兼容)
- InSessionMemory 加 10 stub method 维持扩展 Protocol 兼容

## 关键决策(实施期撞实)
- **DI fallback 走 InSessionMemory**: 测试 / 无 PG env 不 break PR #39 Q4 E behavior, 渐进迁移
- **Industry/Sector 当前 passthrough + audit_flag**: 申万 registry 留 v1.x(Tushare /api/sw_hierarchy 没 ship)
- **cold_start preferences 路留 hook**: User model 当前无 preferences JSONB 列(PR #39 / v0.8 未 ship), 只 seed HOLDS
- **cold_start session_id 用真实 chat_sessions 行**: 每用户一条 'cold_start_system_session' (title 标记), 多次 cold start 复用, 满足 episodes.session_id FK 约束
- **reconciliation case kind**: 'edge_exists_episode_unextracted'(Plan 1B 主 case)+ Plan 2/5 'pending_milvus' / 'age_pg_drift' 留 stub
- **Working blocks paged_lines**: Plan 1B 仅 logger.warning 不真归档; Plan 2 ship archival_memory_insert 后改 真调归档
- **pg_memory_session_factory fixture**: Plan 1B Edit 增量加(契约 § 17 A1 允许 Edit conftest), 提供 callable factory 形式给 HierarchicalMemory DI 用; 跟 Plan 1A 的 pg_memory_fixture(dict[str,Any]返回 'engine'/'url')并存

## 跟 spec 决策对齐
- spec § 1: Memory Protocol DI hook ✓
- spec § 3: 7 entity + 11 rel + normalize 4 类规则 ✓(Industry/Sector v1.x 接 registry)
- spec § 7: persona 500 + scratchpad 1000 + 自动 paging ✓
- spec § 8: 3 路 cold start + 幂等(走 Plan 1A UNIQUE constraint)✓
- spec § 11 末尾 #5: reconciliation 入口骨架 ship ✓(Plan 5 weekly retry job 收束)

## 关键文件 ref
- backend/app/memory/protocol.py
- backend/app/memory/hierarchical.py
- backend/app/memory/registry.py
- backend/app/memory/working_blocks.py
- backend/app/memory/cold_start.py
- backend/app/memory/reconciliation.py
- backend/app/router/chat.py(DI swap)
- backend/tests/integration/memory/conftest.py(pg_memory_session_factory 增量)

## 下游解锁
- Plan 2 写入 8 step pipeline: 在 hierarchical.py 填 archival_memory_insert(Step 2-8)
- Plan 3 读取: 在 hierarchical.py 填 archival_memory_search + RRF v2
- Plan 4 MCP tools: 6 tool 包装本 Plan ship 的 method
- Plan 5 cost optimization: reconciliation Celery weekly job + skip_gate / batch_extractor
