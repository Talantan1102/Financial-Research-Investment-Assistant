---
name: c5-plan3-read-pipeline-done
description: C.5 Plan 3 Read Pipeline + RRF v2 ship — 3-way hybrid + 时间感知 ranking + 长尾监控 + persona auto-injection
type: project
---

C.5 Plan 3 (Read Pipeline + RRF v2) ship — 2026-05-11.

## ship 范围

- **3-way hybrid 检索**:
  - 路径 1 BM25: PG GIN tsvector + jieba pre-tokenize (复用 Plan 1 `jieba_tokenize_for_search`)
  - 路径 2 Vector: Milvus 单 collection + qwen v3 embed
  - 路径 3 Graph: AGE Cypher on-demand, **不进** default search; 由 Plan 4 archival_memory_traverse MCP tool 调用 `graph_traverse` 底层函数. AGE 不可用时 fallback 空 list, 不报错.
- **RRF v2 完整算法** (`backend/app/memory/rrf.py`):
  - `IMPORTANCE_WEIGHT_MAP = {0.9: 0.95, 0.5: 0.75, 0.2: 0.6}`
  - `TAU_DAYS_BY_REL_TYPE = {HOLDS/SOLD: 365, PREFERS/AVOIDS/WATCHES: 180, EXPRESSED_VIEW/STUDIED: 90}`
  - `TAU_DAYS_DEFAULT = 180` / `DECAY_FLOOR = 0.5` / `RRF_K = 60`
  - 历史 edge (valid_to IS NOT NULL) 用 valid_to 作衰减参考点
  - `_now` test injection per § 17 A2-2
- **Working memory auto-injection** (`backend/app/memory/persona_populator.py`):
  - session 起手扫 4 类 edge (HOLDS/PREFERS/AVOIDS/WATCHES current snapshot)
  - 拼 markdown ~500 tokens → UPSERT chat_memory_working_blocks(persona)
  - char-based truncate (1.4 tokens/char) 避免装 tiktoken 依赖
  - chat router `_stream_chat` 头部 hook + 模块级 set 防同 session 重跑
- **长尾召回监控** (`backend/app/memory/long_tail_monitor.py`):
  - top-K valid_from P90 在 instrumentation 落库时计算
  - `compute_long_tail_metrics` 提供给 Plan 8 eval pipeline 算大盘
  - 阈值 7 天: median P90 < 7 → alert
- **Posterior calibration instrumentation** (per § 17 A4):
  - 表名 `chat_memory_retrieval_logs` (search hits)
  - 表名 `chat_memory_retrieval_feedback` (用户 reject/confirm/invalidate)
  - SQL migration `2026-05-11-c5-plan3-instrumentation.sql` (lifespan + test conftest 都 wire)
- **archival_memory_search 替换 Plan 1 stub**: `HierarchicalMemory.archival_memory_search` 完整实现, 含 instrumentation + 错误隔离

## 关键决策 (实施期撞实)

### 1. sync Session pattern, 不引 AsyncEngine
Plan 文件骨架用 `AsyncEngine`, 但 Plan 1B `HierarchicalMemory` DI 已是 sync `pg_session_factory: () -> Session` (契约 § 3). 强行引 AsyncEngine 会破坏 Plan 1B/2A 已 ship 的 archival_memory_insert / working_blocks CRUD. 决定全 Plan 3 沿用 sync Session, 仅 vector_search / graph_traverse 因外部 client 是 awaitable 保留 async 入口.

### 2. archival_memory_search 失败隔离粒度
- BM25 单独 try/except → log warning 不整体失败
- vector 同理 (Milvus 不可用时 fallback BM25-only)
- instrumentation 失败 → log warning, 不 rollback search 结果
- Milvus / embed_service None 时跳过 vector 路径(Plan 1B chat router 注 None 状态需兼容)

### 3. 长尾监控不在 search 路径同步告警
- Plan 3 ship 阶段只落库 P90, 不在 search 路径触发 alert (避免影响 latency).
- Plan 8 eval pipeline 跑 `compute_long_tail_metrics` 周报上大盘.

### 4. persona_populator 异常时不阻塞 chat
- chat router `_stream_chat` 头部 try/except 包 populator
- 失败仅 log warning, session 继续
- 避免 PG 短暂故障导致整个 chat 不可用

### 5. graph_traverse AGE 不可用容错
- spike 假设 AGE 总能用, 实测本地 PG fixture skip AGE (extension 未编译).
- `graph_traverse(age_executor=None)` 直接返空 list, 不报错
- AGE.cypher raise 时也 fallback 空 list (catch + log warning)
- Plan 4 archival_memory_traverse MCP tool 透传该行为

### 6. test 写法上的发现
- `test_archival_memory_search_stub` 在 Plan 1B 已断言 NotImplementedError; Plan 3 ship 后必须改 test (`test_archival_memory_search_no_longer_stub`) 否则 false-fail.
- L1 retriever_e2e 用 mock Milvus (不引真 milvus seed → search 端到端), 真 BM25 + 真 PG seed 已覆盖核心 RRF 排序逻辑. 完整 search end-to-end 留 Plan 8 eval pipeline.

## 跟 spec 决策对齐

- **spec § 5** 全部 (3-way hybrid + RRF + persona auto-injection 完整骨架对齐)
- **spec § 7** working memory budget (persona 500 tokens / 自动 paging 逻辑留 Plan 1B working_blocks helper, populator 写入前 truncate)
- **spec § 11 末尾 #3** 时间感知 RRF 公式 1:1 落地
- **§ 17 A2-2** `compute_time_decay(rel_type, valid_from, valid_to, *, _now=None)` 签名严守, 测试用 `_now` 注入 fake time
- **§ 17 A4** instrumentation 表名 final: `chat_memory_retrieval_logs` + `chat_memory_retrieval_feedback`

## 关键文件 ref

- `backend/app/memory/rrf.py` (常量 + compute_time_decay + reciprocal_rank_fusion_v2)
- `backend/app/memory/retriever.py` (3 路 retriever + format_edges_meta_for_rrf)
- `backend/app/memory/persona_populator.py`
- `backend/app/memory/instrumentation.py` (log_retrieval_hit + log_user_reject)
- `backend/app/memory/long_tail_monitor.py` (compute_long_tail_metrics + fetch_recent_retrieval_logs)
- `backend/app/memory/hierarchical.py::archival_memory_search` (实现替换 Plan 1 stub)
- `backend/scripts/migrations/2026-05-11-c5-plan3-instrumentation.sql`
- `backend/app/app_main.py::lifespan` (新加 instrumentation migration apply)
- `backend/app/router/chat.py::_stream_chat` (session-start persona hook)

## 测试 ship

- L0 Unit: 19+16+9+7 = 51 case
  - test_rrf.py (常量 / compute_time_decay 6 case / reciprocal_rank_fusion_v2 8 case)
  - test_retriever.py (BM25 3 / Vector 5 / Graph 5 / format_edges_meta 3)
  - test_persona_populator.py (format_persona_markdown / truncate / populate_persona 9)
  - test_long_tail_monitor.py (7 case 含 alert / passing / pct_below)
- L1 Integration: 5+3+5 = 13 case
  - test_retriever_e2e.py (高 importance 排首 / 衰减底召回 / 多租户隔离 / mock vector / instrumentation 落库)
  - test_persona_populator_e2e.py (4 类拼装 / placeholder / 幂等 UPSERT)
  - test_instrumentation_e2e.py (schema check / log_retrieval_hit p90 / log_user_reject CHECK constraint)
- L2 Cassette: 留 Plan 8 eval pipeline 集成 (qwen embed + 真 search 端到端). 当前 Plan 3 用 mock Milvus 已覆盖核心 RRF v2 算法行为.

## pending issue

- **archival_memory_traverse MCP tool wrapper** → Plan 4 (本 plan 已提供 graph_traverse 底层)
- **embed_cache hook** → Plan 5 (本 plan vector_search 直接调 embed_service.embed)
- **posterior calibration weekly job** → Plan 5 (本 plan 已落 instrumentation 表)
- **L2 cassette 真 search end-to-end** → Plan 8 eval pipeline (50 golden eval)
- **AGE-available L1 graph traversal test** → 本机 PG image 不带 AGE; CI/真 AGE 环境跑

## 沉淀沿用

- 沿用 Plan 1B `app.memory.registry.jieba_tokenize_for_search` (BM25 切词)
- 沿用 Plan 1B `pg_session_factory` 同步 Session pattern (HierarchicalMemory DI)
- 沿用 Plan 2A `try_milvus_insert` outbox 模式经验 (本 plan 不写, 但 vector_search 拉到 PG join 元数据时同款 _row_to_dict helper)
