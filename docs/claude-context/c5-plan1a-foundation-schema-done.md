---
name: c5-plan1a-foundation-schema-done
description: C.5 Plan 1A foundation schema ship — 4 PG 表 + AGE 图 + Milvus collection + app_main lifespan
type: project
---

C.5 Plan 1A (Foundation Schema) ship — 2026-05-11.

## ship 范围

**PG 4 表**:
- `chat_memory_episodes` — 写入 pipeline 入口 + extracted_at 标记
- `chat_memory_nodes` — entity 节点(7 entity_type ontology)
- `chat_memory_edges` — bi-temporal 4 字段(valid_from / valid_to + recorded_at / invalidated_at)
- `chat_memory_working_blocks` — Tier 1 paging

**SQL migration** (`backend/scripts/migrations/2026-05-11-c5-memory-schema.sql`):
- partial index 加速 active edge 查询(`WHERE invalidated_at IS NULL`)
- GIN tsvector(content_vec)给 BM25 路 jieba_tokenize
- 时间区间索引(valid_from / valid_to)
- AGE 扩展加载 + 'chat_memory' 图 + 7 vlabel + 11 elabel

**Milvus**:
- `chat_memory_edge_embeddings_v1` collection + `chat_memory_edge_embeddings` alias
- 1024d (qwen text-embedding-v3, 与 KB 同维互换)
- alias 模式给 #1 向量升级 hook 留口子

**app_main lifespan**:
- 启动时幂等 apply SQL migration + ensure Milvus collection

**L0 + L1 tests**:
- schema validation 4 model (field / index / constraint)
- 幂等键 + CHECK constraint 反向失败(算法深度补丁 #5 起点)
- AGE 7 vlabel + 11 elabel(AGE 不可用时 skip)

## 关键决策

- **Apache AGE 不上 Neo4j** — 复用 v1.0 PG 基建, 但 PG 存全数据 + AGE 镜像图拓扑, 避开 AGE agtype 索引能力弱
- **Bi-temporal 4 字段** (Snodgrass 1993) — valid-time / transaction-time 严格区分
- **alias 模式 Milvus** — 给 #1 P3 hook (向量模型升级)留口子

## 关键文件 ref

- `backend/scripts/migrations/2026-05-11-c5-memory-schema.sql`
- `backend/app/memory/models.py` 4 SQLAlchemy models
- `backend/app/memory/milvus_setup.py` collection + alias setup
- `backend/app/app_main.py` lifespan integration
