# C.5 Cross-Session Memory — Design Spec

> **Status**: design (2026-05-10 brainstorm 产出)
> **Branch milestone**: v0.10 / 或 v1.x（C.5 P2 hook 兑现）
> **Anchor 上游**:
> - PR #39 ship: `docs/claude-context/v0.9-chat-c1c2-architecture.md`
> - PR #39 spec: `docs/superpowers/specs/2026-05-09-v0.9-chat-mode-c1c2-design.md` § 1.3 决策 3 + § P2 hook
> - v1.0 监控引擎: `docs/claude-context/v1.0-monitoring-engine-done.md`
> **工程量**: 30-38 天（v1.0 监控引擎 ×1.2-1.5）

---

## § 0 元信息与触发（Meta）

### Why this spec

PR #39 ship 时 § 1.3 决策 3 显式记录："in-session memory 走 Q4=E（C + tool dedup + token-guard summarize），D MemGPT-style hierarchical 推到 C.5"。本 spec 兑现 C.5 hook。

### 在 v1 路线图中的位置

| Use case | 状态 | Anchor |
|---|---|---|
| B-1 深度尽调 | v0.8.4 ship | `2026-05-04-v0.8.4-b1-single-deep-design.md` |
| B-3+C-4 持仓监控 | v1.0 ship | `2026-05-08-v1.0-portfolio-monitoring-engine-design.md` |
| C-3 事件追踪 | 留 v1.x | (无 spec) |
| **C.5 Cross-session memory** | **本 spec** | 当前 |

C.5 不是独立 use case，是基础能力 — 接在 PR #39 chat platform 之上，给所有 chat-based 场景（C.1 / C.2 / B-7）一致的长期记忆能力。

### 核心 brainstorm 决策（2026-05-10）

| # | 决策 | 选择 |
|---|---|---|
| 1 | Memory 范式 | **杂交**: Letta MemGPT agent-tool 接口 + Zep KG 后端 |
| 2 | Extraction 触发 | **D**: agent self-managed via tool + end-of-session 兜底批 |
| 3 | Graph DB | **PG + Apache AGE**（不上 Neo4j，复用 v1.0 PG 基建）|
| 4 | Ontology 模式 | **Prescribed seed + drift-tolerant**（7 entity + 11 rel + audit drift）|
| 5 | Milvus collection | **单 collection (edges only with rich embed text)**，node collection 留 v1.x |
| 6 | Graph traversal | **on-demand 单独 tool**（不进 default search，避免 entity extraction 强加 latency overhead）|
| 7 | Tool API surface | **6 MCP tools** in 独立 `memory` server profile |
| 8 | 工业难题撞实 | **16 个 全 surface** + spec 内每条带 paper ref + 方案 + 验证 |
| 9 | Cost optimization | **5 项 ladder**（prompt cache / batch / skip gate / async / embedding cache）|

---

## § 1 整体架构

### 一句话定义

**杂交（hybrid）**：Letta MemGPT 论文（2023）的"agent-self-managed memory"tool 抽象 + Zep / Graphiti 论文（Jan 2025）的"temporal knowledge graph"后端 + Anthropic Skills 风的可移植 skill packaging（PR #39 同源）。

### 设计目标

1. **Agent 友好**：agent 通过 6 个标准 tool 操作 memory，跟 Letta 接口对齐，简洁
2. **金融 domain 友好**：bi-temporal 原生支持"想法演化"（用户 2024 看好茅台，2025 改观）
3. **作品集叙事强**：撞实 16 个工业难题，每条带 paper / 产品 ref + 验证
4. **工业级 ops 一致**：复用 v1.0 PG 基建，不引 Neo4j 增加运维代价

### 3 层（3-tier）记忆结构

```
┌─────────────────────────────────────────────────────────┐
│ Tier 1: Working Memory（工作记忆）                       │
│   永远在 prompt 里的 ~1500 tokens                        │
│   ├─ persona block: 500 tokens (用户长期画像)            │
│   └─ scratchpad block: 1000 tokens (当下任务工作笔记)    │
│   存储: chat_memory_working_blocks 表                    │
│   Agent 操作: core_memory_append / core_memory_replace   │
│   类比: 大脑当下 hold 的几条信息                         │
└─────────────────────────────────────────────────────────┘
                  ↑↓ tool 调用主动 page 进出
┌─────────────────────────────────────────────────────────┐
│ Tier 2: Archival Memory（归档记忆）— Zep KG              │
│   长期事实图，bi-temporal（双时态）                      │
│   存储: PG 表（含 4 timestamps）+ AGE 图镜像 + Milvus 向量│
│   Agent 操作: archival_memory_insert / search / traverse │
│   类比: 长期记住的事实，可跨年                           │
└─────────────────────────────────────────────────────────┘
                  ↑ semantic / graph search
┌─────────────────────────────────────────────────────────┐
│ Tier 3: Recall Memory（回忆记忆）                        │
│   所有历史 chat message 全保留                           │
│   存储: 复用 chat_messages 表（PR #39 已有）             │
│   Agent 操作: recall_memory_search                       │
│   类比: "上次说过但记不清原话"，有线索回溯               │
└─────────────────────────────────────────────────────────┘
```

### 数据流（Data flow）

**写入路径**：
1. Agent in chat 调 `archival_memory_insert(content, reasoning, importance)` 主动写
2. session 结束时，end-of-session 兜底批扫所有未抽取 episodes，cheap LLM 补抽
3. 写入时 bi-temporal 自动处理冲突（事实演化 vs 系统纠错）

**读取路径**：
1. Agent in chat 调 `archival_memory_search` / `archival_memory_traverse` / `recall_memory_search`
2. session 起手 auto-populate persona block from graph

### 跟 PR #39 的关系

| 模块 | PR #39 已有 | C.5 新加 |
|---|---|---|
| Memory protocol | ✓ DI hook（`InSessionMemory` impl）| `HierarchicalMemory` impl 替换 |
| LangGraph supervisor | ✓ context_node → planner → tool/responder | 不动 |
| MCP server | ✓ 6 tool in `chat_tools` profile | 加 `memory` profile（独立 6 tool）|
| AsyncPostgresSaver | ✓ langgraph_checkpoints schema | 不动（C.5 走自己的 schema）|
| Celery + Redis | ✓ async task infra | 复用跑 end-of-session extraction batch |
| Skill loader L1/L2/L3 | ✓ | 不动（memory 跟 skill 同 MCP transport）|
| Frontend AppShell | ✓ chat-first sidebar | 加 `/memory` 路由 + Cytoscape viz |

---

## § 2 数据模型 / Schema

### 总览

```
PG 数据库（不引新服务）
├── chat_memory_episodes       ← 抽取单位
├── chat_memory_nodes          ← 实体
├── chat_memory_edges          ← 关系（含 4 时间戳）
├── chat_memory_working_blocks ← persona / scratchpad
└── (扩展) AGE 图 'chat_memory' ← 节点/边镜像（拓扑），用 Cypher 做图遍历
                                  AGE = Apache Graph Extension，PG 内置图扩展

Milvus（已有）
└── chat_memory_edge_embeddings ← edge 向量 (qwen v3 1024d)
                                   单 collection: edge 嵌入文本含 source/target labels
```

### 设计取舍：PG 表 + AGE 镜像

AGE 把所有 properties 存成 `agtype`（JSON-like），**没法对 `valid_from / valid_to` 这些时间戳建 B-tree 索引**。"当前快照"query 会全表扫，~30ms（500 边时）。

→ **杂交方案**：PG 普通表存全数据（B-tree 索引飞快），AGE 只存图拓扑（拿 ID）。Cypher traversal 走 AGE，时间区间 query 走 PG。两路都快。

### 表 1: `chat_memory_episodes`（情节）

```sql
CREATE TABLE chat_memory_episodes (
  episode_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id             UUID NOT NULL REFERENCES users(id),
  session_id          UUID NOT NULL REFERENCES chat_sessions(id),
  episode_index       INTEGER NOT NULL,
  user_message_text   TEXT NOT NULL,
  agent_response_text TEXT,
  source_kind         TEXT NOT NULL DEFAULT 'chat_turn',
                      -- chat_turn / file_upload / web_paste / cold_start_seed
  extracted_at        TIMESTAMPTZ,
  extracted_by        TEXT,                     -- 'agent' / 'eos_batch' / 'manual'
  extraction_metadata JSONB,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(session_id, episode_index)
);

CREATE INDEX idx_episodes_user_session ON chat_memory_episodes(user_id, session_id);
CREATE INDEX idx_episodes_unextracted  ON chat_memory_episodes(user_id) 
  WHERE extracted_at IS NULL;       -- partial index, eos_batch 扫这些
```

### 表 2: `chat_memory_nodes`（节点 / 实体）

```sql
CREATE TABLE chat_memory_nodes (
  node_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id        UUID NOT NULL REFERENCES users(id),
  entity_type    TEXT NOT NULL,                  -- 7 类（§ 3 ontology）
  entity_label   TEXT NOT NULL,                  -- ts_code / 'User' / 行业名 / metric 名
  properties     JSONB DEFAULT '{}',
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  search_tokens  TEXT,                           -- jieba pre-tokenize 中文分词
  search_vector  tsvector GENERATED ALWAYS AS (
    to_tsvector('simple', coalesce(search_tokens, ''))
  ) STORED,
  UNIQUE(user_id, entity_type, entity_label)
);

CREATE INDEX idx_nodes_user_type  ON chat_memory_nodes(user_id, entity_type);
CREATE INDEX idx_nodes_search_gin ON chat_memory_nodes USING GIN(search_vector);
```

### 表 3: `chat_memory_edges`（关系，含 bi-temporal 核心）

```sql
CREATE TABLE chat_memory_edges (
  edge_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id           UUID NOT NULL REFERENCES users(id),
  source_node_id    UUID NOT NULL REFERENCES chat_memory_nodes(node_id),
  target_node_id    UUID NOT NULL REFERENCES chat_memory_nodes(node_id),
  rel_type          TEXT NOT NULL,                  -- 11 类（§ 3 ontology）

  -- ====== bi-temporal 4 字段 ======
  valid_from        TIMESTAMPTZ NOT NULL,            -- 事实在现实里何时开始为真
  valid_to          TIMESTAMPTZ,                     -- 何时结束为真（null = 仍有效）
  recorded_at       TIMESTAMPTZ NOT NULL DEFAULT now(),  -- 系统何时记录
  invalidated_at    TIMESTAMPTZ,                     -- 系统何时认为这条记录"错了"

  -- ====== provenance ======
  source_episode_id UUID NOT NULL REFERENCES chat_memory_episodes(episode_id),
  importance        REAL CHECK (importance BETWEEN 0 AND 1),
  reasoning         TEXT,

  properties        JSONB DEFAULT '{}',
  search_tokens     TEXT,
  search_vector     tsvector GENERATED ALWAYS AS (
    to_tsvector('simple', coalesce(search_tokens, ''))
  ) STORED
);

CREATE INDEX idx_edges_user_rel              ON chat_memory_edges(user_id, rel_type);
CREATE INDEX idx_edges_source                ON chat_memory_edges(source_node_id);
CREATE INDEX idx_edges_target                ON chat_memory_edges(target_node_id);
CREATE INDEX idx_edges_episode               ON chat_memory_edges(source_episode_id);
CREATE INDEX idx_edges_search_gin            ON chat_memory_edges USING GIN(search_vector);

-- 关键: partial index for "current snapshot" query (90%+ query 走这个)
CREATE INDEX idx_edges_current_snapshot 
  ON chat_memory_edges(user_id, source_node_id, target_node_id) 
  WHERE valid_to IS NULL AND invalidated_at IS NULL;

-- 时间区间 query 索引
CREATE INDEX idx_edges_valid_range 
  ON chat_memory_edges(user_id, valid_from, valid_to);
```

### Bi-temporal 4 字段的 3 个场景示例

**场景 1**：用户 2025-03-15 chat 说"我 2024-08 买了 500 股茅台"
```
INSERT edge_1 (HOLDS, valid_from=2024-08-01, valid_to=null, 
               recorded_at=2025-03-15, invalidated_at=null)
```

**场景 2**：用户 2025-09-01 又说"茅台我 3 月清了"（**现实里事实结束**）
```
UPDATE edge_1 SET valid_to = 2025-03-31     -- 不改 invalidated_at!
INSERT edge_2 (SOLD, valid_from=2025-03-31)
```

**场景 3**：用户 2025-12-01 说"我之前记错了，根本没买茅台是五粮液"（**系统记错**）
```
UPDATE edge_1, edge_2 SET invalidated_at = now()  -- 不改 valid_to!
INSERT edge_3 (HOLDS, target=五粮液, valid_from=2024-08-01)
```

**关键**：valid_to（事实结束）vs invalidated_at（记录纠错）语义完全不同 — 金融审计场景 categorical 必要。

Audit query：
```sql
-- "我们曾经记错过什么"
SELECT * FROM chat_memory_edges
WHERE user_id = $1 AND invalidated_at IS NOT NULL
ORDER BY invalidated_at DESC;
```

### 表 4: `chat_memory_working_blocks`

```sql
CREATE TABLE chat_memory_working_blocks (
  block_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id      UUID NOT NULL REFERENCES users(id),
  block_name   TEXT NOT NULL,                  -- 'persona' / 'scratchpad'
  content      TEXT NOT NULL DEFAULT '',
  token_count  INTEGER NOT NULL DEFAULT 0,
  max_tokens   INTEGER NOT NULL,               -- persona=500, scratchpad=1000
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(user_id, block_name)
);
```

### AGE 图设置

```sql
CREATE EXTENSION IF NOT EXISTS age;
LOAD 'age';
SET search_path = ag_catalog, "$user", public;

SELECT create_graph('chat_memory');

-- 7 节点标签
SELECT create_vlabel('chat_memory', 'User');
SELECT create_vlabel('chat_memory', 'Stock');
SELECT create_vlabel('chat_memory', 'Industry');
SELECT create_vlabel('chat_memory', 'Sector');
SELECT create_vlabel('chat_memory', 'Metric');
SELECT create_vlabel('chat_memory', 'Strategy');
SELECT create_vlabel('chat_memory', 'Concept');

-- 11 边标签
SELECT create_elabel('chat_memory', 'HOLDS');
SELECT create_elabel('chat_memory', 'WATCHES');
SELECT create_elabel('chat_memory', 'PREFERS');
SELECT create_elabel('chat_memory', 'AVOIDS');
SELECT create_elabel('chat_memory', 'EXPRESSED_VIEW');
SELECT create_elabel('chat_memory', 'SOLD');
SELECT create_elabel('chat_memory', 'STUDIED');
SELECT create_elabel('chat_memory', 'COMPARED');
SELECT create_elabel('chat_memory', 'BELONGS_TO');
SELECT create_elabel('chat_memory', 'HAS_CONCEPT');
SELECT create_elabel('chat_memory', 'CORRELATED_WITH');
```

### Milvus 集合

```python
collection = "chat_memory_edge_embeddings"
schema = {
    "edge_id": Int64,                      # 引用 PG chat_memory_edges.edge_id
    "user_id": VarChar(36),                # 多用户隔离
    "embedding": FloatVector(1024),        # qwen v3 embed
    "rel_type": VarChar(32),
}
# Edge embed text 模板：
# "{rel_type} {source_entity_type} {source_label} →
#  {target_entity_type} {target_label}
#  reasoning='{reasoning}' props={properties_json}"
```

### Schema 设计的 4 个简历叙事点

1. **PG + AGE 镜像**：解 AGE agtype 索引能力弱的问题，避开 Neo4j 运维代价
2. **Bi-temporal partial index**：高频 "current snapshot" query 走小索引（500 边里只索引 ~20 条）
3. **GIN tsvector + Milvus + AGE 三路检索基建**：§ 5 hybrid retrieval 直接用
4. **Provenance FK first-class**：每条 edge 强制 FK 到 source episode（NOT NULL），解锁审计 / 纠错 / GDPR

---

## § 3 Ontology（本体）

### 设计哲学：Prescribed seed + drift-tolerant

**不是**纯 prescribed（强 ENUM 约束），**也不是**纯 learned（任意 LLM-emergent）。是工业主流杂交：
- LLM extraction prompt 给 7+11 个 "preferred categories"
- DB schema 用 TEXT 字段不 ENUM 强制
- 周期性 audit query 检测 drift，决定接受新类型 or 改 prompt

跟 Graphiti / LangChain LLMGraphTransformer / mem0 / Neo4j LLM KG Builder 在金融 domain 的 production 配置一致。

### 7 节点类型

| 类型 | 含义 | label 取值 | 例子 | 来源 |
|---|---|---|---|---|
| **User** | 用户本人 | UUID | 你（dogfood 单用户）| cold start 自动建 |
| **Stock** | 个股 | Tushare ts_code | `'600519.SH'` 茅台 | chat 提及 / 持仓表 seed |
| **Industry** | 二/三级行业 | 申万行业名 | `'白酒'`、`'股份制银行'` | Tushare cold seed |
| **Sector** | 一级行业 | 申万一级 | `'食品饮料'`、`'金融'` | Tushare cold seed |
| **Metric** | 财务/估值指标 | metric 名 | `'PE'`、`'ROE'`、`'cash_flow'` | 写死白名单 (~30) |
| **Strategy** | 投资方法论 | 方法名 | `'DCF'`、`'价值投资'` | 写死白名单 (~20) |
| **Concept** | 主题概念 | concept 名 | `'国产替代'`、`'AI 大模型'` | Tushare concept + chat 提取 |

### 11 关系类型

**8 类 user-derived**（chat 抽出）：

| 关系 | source → target | 含义 / properties |
|---|---|---|
| **HOLDS** | User → Stock | 持有：qty / avg_cost / thesis |
| **WATCHES** | User → Stock/Sector/Concept | 关注未持有：since |
| **PREFERS** | User → Metric/Strategy/Sector | 偏好：priority |
| **AVOIDS** | User → Sector/Stock/Concept | 规避：reason |
| **EXPRESSED_VIEW** | User → Stock/Sector/Concept | 观点：sentiment / view_text |
| **SOLD** | User → Stock | 已卖：sale_date / reason |
| **STUDIED** | User → Stock/Sector | 深入研究：depth / report_id |
| **COMPARED** | User → Stock 对 | 对比：dimension / conclusion |

**3 类 structural**（cold start seed，全用户共享）：

| 关系 | 例子 | 来源 |
|---|---|---|
| **BELONGS_TO** | Stock 茅台 → Industry 白酒 → Sector 食品饮料 | Tushare industry 字段 |
| **HAS_CONCEPT** | Stock 茅台 → Concept 食品安全 | Tushare 概念字段 |
| **CORRELATED_WITH** | Industry 白酒 ↔ Sector 消费 | 预算的相关性矩阵（v1.x 留口）|

### Drift detection audit query

```sql
-- 每周跑一次：检测 LLM 抽出 ontology 外的类型
SELECT rel_type, count(*)
FROM chat_memory_edges
WHERE rel_type NOT IN ('HOLDS','WATCHES','PREFERS','AVOIDS',
                       'EXPRESSED_VIEW','SOLD','STUDIED','COMPARED',
                       'BELONGS_TO','HAS_CONCEPT','CORRELATED_WITH')
  AND created_at > now() - interval '7 days'
GROUP BY rel_type
ORDER BY count(*) DESC;
```

发现新类型时：
- count > 5 且语义合理 → 加进 ontology（spec + extraction prompt）
- count > 5 但语义重复现有 → 改 extraction prompt 加更严的 type discrimination
- count ≤ 5 → 当 noise 忽略

### Entity normalization 规则

LLM 抽出的 entity_label 可能不一致（"茅台" / "贵州茅台" / "Maotai"），写库前过 registry：

```python
async def normalize_entity(entity_type, entity_label, user_id):
    if entity_type == "Stock":
        return await tushare_registry.lookup(entity_label)  # → '600519.SH'
    elif entity_type == "Industry":
        return shenwan_registry.normalize(entity_label)
    elif entity_type == "Metric":
        return metric_registry.normalize(entity_label)
    # ... 其他类型走对应 registry
```

未匹配时：写库带 `properties.normalization_failed = true`，agent 后续 ask user clarify。

---

## § 4 写入 Pipeline

### 总览：双触发 + 8 step

```
chat turn 结束
    ↓
[Step 1] Episode 入库 (PG INSERT, extracted_at=NULL)
    ↓
两条触发路径：
    ├── Path A: Agent-triggered
    │      chat 进行中 agent 调 archival_memory_insert
    │      → 立即走 Step 2-8
    │
    └── Path B: End-of-session 兜底批
           触发：user 关闭 / idle 30min / 创新 chat
           → 扫所有 extracted_at IS NULL → 批量走 Step 2-8
```

### Step 1: Episode 入库

每次 chat turn 完成 → FastAPI handler 同步 INSERT chat_memory_episodes（前 § 2 已展开）。

### Step 2: LLM Extraction

**Path A 跳过**（agent 已给半结构化 content）。

**Path B 跑 LLM 抽**。Prompt 模板（pseudo-）：

```
你帮金融 chat agent 从对话中抽"用户事实"，存入 graph memory。

# Ontology（你只能用这些类型）
Entity types: User / Stock / Industry / Sector / Metric / Strategy / Concept
Relationship types: HOLDS / WATCHES / PREFERS / AVOIDS / EXPRESSED_VIEW / SOLD / STUDIED / COMPARED

# Entity 命名规则
- Stock: entity_label = ts_code（'600519.SH'）
- Industry: 申万二级
- Metric/Strategy/Concept: 中英文混合白名单（见附录 A）

# 规则
- 只抽用户**显式表达**的事实
- 不确定标 importance < 0.5
- "我之前 X 但现在 Y" → 抽两条 edge：
  - 第一条 valid_from=之前, valid_to=now()
  - 第二条 valid_from=now()

# Episode
User: {user_message}
Agent: {agent_response}

# 输出 JSON schema (Pydantic 强 validation)
{
  "entities": [{"entity_type": str, "entity_label": str, "properties": dict}],
  "edges": [{
      "rel_type": str,
      "source_label": str, "target_label": str,
      "valid_from": str, "valid_to": str | null,
      "importance": float, "reasoning": str,
      "properties": dict
  }]
}
```

**模型**：Haiku 4.5（高频 cheap）。

### Step 3: Entity Normalization

走 § 3 normalize 规则。失败的标记 audit flag。

### Step 4: Existing Edges Query

```sql
SELECT * FROM chat_memory_edges
WHERE user_id = $1 AND source_node_id = $2 
  AND rel_type = $3 AND target_node_id = $4
  AND invalidated_at IS NULL
ORDER BY valid_from DESC LIMIT 5;
```

返回 0 → 直接 INSERT；返回 ≥1 → 进 Step 5。

### Step 5: Conflict Resolution（LLM-judge）

4-action prompt：

```
新事实: {new_edge}
现有事实: {existing_edges}

判定 action:
- update_validity: 现实演化（买了→卖了 / 看法改变）
   → existing.valid_to = new.valid_from, INSERT new
- contradict_existing: 系统记错（用户澄清纠正）
   → existing.invalidated_at = now(), INSERT new
- append_new: 不矛盾，独立存在
   → INSERT new
- no_op: 完全重复
   → 跳过

输出 JSON: {"action": "...", "reasoning": "..."}
```

**模型**：Haiku（cheap）。**失败 fail-safe**: 默认 append_new（保守，不丢信息）。

### Step 6: Apply Action

按 LLM 决策 update existing + INSERT new（详细 SQL 见 spec 附录 B）。

### Step 7: Sync to AGE + Milvus

**AGE**（PG 同事务）：

```python
await txn.execute("""
    SELECT * FROM cypher('chat_memory', $$
        MATCH (s {node_id: $src}), (t {node_id: $tgt})
        CREATE (s)-[r:%s {edge_id: $eid}]->(t)
    $$ % rel_type, %s) AS (v agtype)
""", {...})
```

**Milvus**（**outbox pattern** — 不进 PG 事务）：

```python
try:
    embedding = await qwen_embed(edge_text)
    await milvus.insert(...)
except Exception as e:
    # 不 rollback，写 retry queue
    await pg.execute("""
        INSERT INTO pending_milvus_inserts (edge_id, retry_count, last_error)
        VALUES ($1, 0, $2)
    """, edge.edge_id, str(e))
```

后台 Celery job 每 5 分钟扫 pending_milvus_inserts 重试。

### Step 8: 标记 Episode 已抽取

```sql
UPDATE chat_memory_episodes
SET extracted_at = now(),
    extracted_by = $1,                   -- 'agent' / 'eos_batch'
    extraction_metadata = $2             -- {model, edge_count, latency_ms}
WHERE episode_id = $3;
```

### Cost Optimization Layer（5 项 ladder）

减少 LLM 调用成本，每条都是独立简历讲点：

| # | 优化 | 实现 | 节省 |
|---|---|---|---|
| **1** | **Anthropic prompt caching** | extraction_prompt + conflict_judge_prompt 的 system 部分（~1K token）走 cache，5min lifetime | input cost -80% |
| **2** | **Batch extraction** | end-of-session 把 5 个 episode 拼一个 LLM call，让 LLM 标 fact 归属 episode_id | -40% token (system prompt 摊薄) |
| **3** | **Skip-extraction gate** | LLM call 前过 heuristic：episode < 50 字 / 无 ts_code/metric/strategy 关键词 / agent path 已抽过 → skip | -60-70% session 直接 skip |
| **4** | **Async via Celery** | end-of-session extraction 走 PR #39 已有 Celery `llm` 队列，不阻塞用户 | latency 优化（用户感知快）|
| **5** | **Embedding cache** | qwen embed 结果按 `hash(text)` 缓存到 Redis（PR #39 已有），TTL 24h | embedding API call -40% |

**单 session 成本预算**（dogfood scale）：
- 无优化: $0.025
- + 1 (prompt cache): $0.012
- + 2 (batch): $0.008
- + 3 (skip gate): $0.003
- 目标：≤ $0.005

### 失败处理矩阵

| 失败点 | 行为 | retry |
|---|---|---|
| LLM extraction 失败 / invalid JSON | episode 标 extracted_at=NULL，下次 batch 重试 | max 3 次 alert |
| Entity normalization 失败 | 写库带 audit flag | 不 retry |
| Conflict-judge 失败 | 默认 append_new（保守）| 不 retry |
| AGE sync 失败 | PG 事务 rollback | 整批重试 |
| Milvus 失败 | 写 pending_milvus_inserts | 后台 5min 重试 |
| PG 主事务失败 | 全 rollback | max 3 次 |

---

## § 5 读取 Pipeline

### 总览：3-way Hybrid + RRF Fusion

```
agent.archival_memory_search(query, k=5)
     ↓
     ├──────────────────┬──────────────────┬─────────────────┐
  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
  │ 路径 1: BM25  │  │ 路径 2: Vector│  │ 路径 3: Graph │
  │ PG GIN +     │  │ Milvus +     │  │ AGE Cypher   │
  │ jieba 中文分词│  │ qwen v3      │  │ on-demand    │
  │ ~5ms         │  │ ~30ms        │  │ ~50ms        │
  │ 词法匹配      │  │ 语义匹配      │  │ 拓扑邻居      │
  └──────────────┘  └──────────────┘  └──────────────┘
                ↓
       ┌─────────────────┐
       │ RRF Fusion       │
       │ score = Σ 1/(60+ │
       │ rank_in_retr)    │
       └─────────────────┘
                ↓
            top-K (=5)
                ↓
       格式化为 fact triples 给 agent
```

### 路径 1: BM25（PG GIN）+ jieba 中文分词

PG 默认 `to_tsvector('simple', text)` 是空格切词，中文连续字符当 1 token，BM25 失效。

→ **jieba pre-tokenize 方案**：写库前用 `jieba.cut_for_search()` 把"贵州茅台"切成"贵州 / 茅台 / 贵州茅台"，存独立 `search_tokens` 列。

```python
async def bm25_search(query, user_id, k=10):
    query_tokens = " ".join(jieba.cut_for_search(query))
    rows = await pg.fetch("""
        SELECT edge_id, ..., 
               ts_rank(search_vector, plainto_tsquery('simple', $1)) AS bm25_score
        FROM chat_memory_edges
        WHERE user_id = $2 
          AND invalidated_at IS NULL
          AND search_vector @@ plainto_tsquery('simple', $1)
        ORDER BY bm25_score DESC LIMIT $3
    """, query_tokens, user_id, k)
    return [dict(r) for r in rows]
```

**为啥不装 zhparser PG 扩展**：要 root 装扩展，托管 PG 服务（云）支持参差。jieba pre-tokenize 不依赖 PG 扩展可移植。

### 路径 2: Vector（Milvus）—— 单 collection

Edge embed text 模板：

```
"{rel_type} {source_entity_type} {source_label} →
 {target_entity_type} {target_label}
 reasoning='{reasoning}' props={properties_json}"
```

**为啥单 collection 而不是双 collection (node + edge)**：
- Edge embed 文本已含 source/target labels，"茅台" query 直接命中提到茅台的所有 edges
- Node collection 多余：dogfood scale 下 cut-off 风险小，Pattern 1 (entity-anchor) 召回边际收益小
- 单 collection 省 50% Milvus infra + 写入快一倍
- v1.x 真发现召回率不够再加 node collection

### 路径 3: Graph（AGE Cypher）—— on-demand 单独 tool

**默认不进 search**：traverse 需要 start_label，从 free-text query 自动抽 entity 加 +200-500ms LLM call latency。

→ 单独 tool `archival_memory_traverse(start_label, hops, rel_types)`。System prompt 给 trigger 词清单（"相关 / 同 / 之间 / 属于 / 链 / 上下游"），agent 自己判断。

```python
async def graph_traverse(start_label, hops=2, rel_types=None, user_id=None):
    cypher = f"""
        MATCH path = (start {{entity_label: $label, user_id: $uid}})-[*1..{hops}]-(end)
        WHERE all(e IN relationships(path) WHERE 
                  type(e) IN $rel_types AND e.invalidated_at IS NULL)
        RETURN path LIMIT 20
    """
    age_result = await age.cypher('chat_memory', cypher, ...)
    return expand_paths_with_pg_metadata(age_result)
```

### RRF Fusion

```python
def reciprocal_rank_fusion(retriever_results, k=60, top=5):
    scores = defaultdict(float)
    for retriever_list in retriever_results:
        for rank, item in enumerate(retriever_list, start=1):
            scores[item["edge_id"]] += 1.0 / (k + rank)
    sorted_ids = sorted(scores.keys(), key=lambda x: -scores[x])
    return [items_by_id[eid] for eid in sorted_ids[:top]]
```

**为啥 RRF 而不是 weighted score sum**：
- BM25 ts_rank (0-1) vs Milvus L2 距离 (0-2) 量纲不同
- RRF 只用 rank，鲁棒
- 工业广用：Elasticsearch / Pinecone / Vespa hybrid 默认

### Working Memory Auto-Injection（每 session 起手）

```python
async def populate_persona_on_session_start(user_id):
    # 1. 当前持仓
    holdings = await pg.fetch("...HOLDS...valid_to IS NULL...")
    # 2. 偏好
    preferences = await pg.fetch("...PREFERS...")
    # 3. 规避
    avoids = await pg.fetch("...AVOIDS...")
    # 4. 关注
    watches = await pg.fetch("...WATCHES...")
    # 5. 拼 markdown ~500 tokens
    persona_text = format_persona_markdown(holdings, preferences, avoids, watches)
    # 6. UPDATE working_memory_blocks
    await pg.execute("UPDATE chat_memory_working_blocks SET content = $1 ...", persona_text)
```

生成 persona 实例：

```markdown
## 用户画像（auto-generated from memory graph）
### 当前持仓
- 茅台 600519.SH (since 2024-08, qty=500, thesis: cash flow 稳)
- 招商银行 600036.SH (since 2025-09, qty=200)

### 偏好方法（PREFERS）
- DCF (priority 0.9), 价值投资 (priority 0.8)

### 偏好指标
- cash_flow, ROE

### 规避
- 新能源 sector (政策不确定 + 估值贵)

### 关注但未持仓
- 五粮液 000858.SZ, AI 大模型 concept
```

---

## § 6 Agent Tool API（6 MCP Tools）

### Tool inventory

| Tier | Tool | 用途 | 频次 |
|---|---|---|---|
| Tier 1 写 | `core_memory_append` | 持久化 fact 加进 persona/scratchpad | 中 |
| Tier 1 写 | `core_memory_replace` | 替换 working memory 段 | 低 |
| Tier 2 写 | `archival_memory_insert` | 写 fact 进 graph | 中 |
| Tier 2 读 | `archival_memory_search` | 三路 hybrid 检索（默认）| **高** |
| Tier 2 读 | `archival_memory_traverse` | 显式 graph 多跳 | 低 |
| Tier 3 读 | `recall_memory_search` | 搜过去 chat 原文 | 低 |

### Tool schemas（Pydantic 强 validation，关键字段）

详细 schema 见附录 C，关键决策：

- `core_memory_append.content` max 200 chars/call（防 spam）
- `core_memory_append` 超 max_tokens **不报错**，触发自动 paging（archive oldest line + 裁剪），MemGPT 哲学
- `core_memory_replace.old_content` 必须 exact match（类似 Edit tool 防模糊改错）
- `archival_memory_insert` 内部跑完整 § 4 写入 pipeline（封装复杂度）
- `archival_memory_search.k` 默认 5，max 20
- `archival_memory_traverse.hops` 默认 2，max 3（防爆炸）
- 所有 tool 返回带 `source_episode_id` 让 agent 可 chain 调 recall_memory_search 拿原话

### System Prompt 模板（注入 ChatPlanner / Responder）

```
# Memory Tool Usage

You have a 3-tier hierarchical memory system.

## Tier 1: Working Memory (always visible below)
{{persona_block}}
{{scratchpad_block}}

To modify these blocks (for facts that should persist across chats):
- core_memory_append("persona", content): for short durable facts
- core_memory_replace("persona", old, new): for updating

## Tier 2: Archival Memory (graph)

For longer / less central facts → write to graph:
- archival_memory_insert(content, reasoning, importance)

To recall from graph:
- archival_memory_search(query, k) — DEFAULT for "what did I say about X"
- archival_memory_traverse(start_label, hops, rel_types) — ONLY when user asks:
  - 关系链 ("跟我持仓相关的", "同行业的")
  - 拓扑 ("所属行业的其他股", "...产业链")
  Trigger words: 相关 / 同 / 之间 / 属于 / 链 / 上下游

If traverse returns empty → fall back to search.

## Tier 3: Recall Memory (chat history)

For "我们上次聊过 X" / "你之前说过 Y" → use:
- recall_memory_search(query, k)

## Memory hygiene rules

1. Don't write memory for one-off questions without user expressing facts
2. Prefer archival_memory_insert over core_memory_append when uncertain
3. importance scale: 0.9-1.0 explicit identity / 0.5-0.8 contextual / 0.3-0.5 weak signal
4. Provenance auto-tracked via source_episode_id
```

### Integration with PR #39 MCP server

```yaml
# mcp_servers.yaml additions
servers:
  - name: chat_tools          # 已有 PR #39
    transport: stdio
    command: ["python", "-m", "app.mcp_server.server", "--profile", "chat_tools"]
  - name: memory              # NEW C.5
    transport: stdio
    command: ["python", "-m", "app.mcp_server.server", "--profile", "memory"]
```

```
backend/app/mcp_server/tools/
├── existing/                   # PR #39
└── memory/                     # NEW C.5
    ├── core_memory_append.py
    ├── core_memory_replace.py
    ├── archival_memory_insert.py
    ├── archival_memory_search.py
    ├── archival_memory_traverse.py
    └── recall_memory_search.py
```

**为啥独立 memory MCP server**：
1. Capability isolation：memory 是横切，可被其他 use case 复用
2. 生命周期独立：memory server fail 不影响 chat tool server
3. Skill packaging 可移植到 Claude Code skills
4. v1.x 多用户时方便独立 authz

### Tool routing 监控 + eval

```sql
-- 周报查 hit rate
SELECT tool_name, COUNT(*) AS calls,
       AVG(CASE WHEN result_count > 0 THEN 1 ELSE 0 END) AS hit_rate,
       AVG(latency_ms) AS p50_latency
FROM mcp_tool_call_log
WHERE tool_name LIKE '%memory%'
  AND created_at > now() - interval '7 days'
GROUP BY tool_name;
```

**期待**：search hit > 80% / traverse hit > 50% / recall > 70%。

**Eval 50 golden case** 跑 routing accuracy ≥ 0.85（PR #39 plan_id router 同标准）。

---

## § 7 Working Memory Budget

**总预算**：1500 tokens 在 system prompt 里 reserved。

| Block | tokens | 用途 |
|---|---|---|
| **persona** | 500 | 用户长期画像（持仓 / 偏好 / 规避 / 关注）|
| **scratchpad** | 1000 | 当前 session agent 工作笔记 |

**超 budget 行为**：自动 paging 而非报错：
1. 拿 oldest line（按 line break 切）
2. 调 archival_memory_insert 把 oldest line 归档进 graph（带 source episode = 上次 paging 时的 session）
3. 从 block content 裁掉 oldest line
4. 新 content append

这是 MemGPT 论文核心创新（OS-style virtual memory），spec 显式实现。

**Token counter 选用**：跟 main chat agent 用同 tokenizer（PR #39 用 tiktoken/qwen，C.5 沿用）。

---

## § 8 Cold Start Populator

新用户首次 chat 时，从已有 PG 数据 seed graph，避免空 memory。

### 触发机制

```python
async def on_chat_session_create(user_id, session_id):
    # 检查是否已 cold start
    seeded = await pg.fetchval("""
        SELECT EXISTS (
          SELECT 1 FROM chat_memory_episodes
          WHERE user_id = $1 AND source_kind = 'cold_start_seed'
        )
    """, user_id)
    if not seeded:
        await seed_user_graph(user_id)
```

### 3 路数据源

```python
async def seed_user_graph(user_id):
    # 创建 cold-start episode 让所有 seed edges 有 provenance
    seed_episode_id = await pg.fetchval("""
        INSERT INTO chat_memory_episodes (
          episode_id, user_id, session_id, episode_index,
          user_message_text, agent_response_text, source_kind,
          extracted_at, extracted_by
        ) VALUES (
          gen_random_uuid(), $1, NULL, 0,
          'COLD_START_SEED', 'COLD_START_SEED', 'cold_start_seed',
          now(), 'cold_start'
        ) RETURNING episode_id
    """, user_id)
    
    # 1. 持仓 → HOLDS edges
    positions = await pg.fetch(
        "SELECT ts_code, qty, avg_cost FROM positions WHERE user_id = $1",
        user_id
    )
    for p in positions:
        await insert_edge(
            user_id=user_id,
            source_label="User", source_type="User",
            target_label=p["ts_code"], target_type="Stock",
            rel_type="HOLDS",
            valid_from=p["acquired_at"] or "2024-01-01",
            properties={"qty": p["qty"], "avg_cost": p["avg_cost"]},
            source_episode_id=seed_episode_id,
            importance=1.0,
            reasoning="cold start from positions table"
        )
    
    # 2. 偏好 → PREFERS edges
    user = await pg.fetch_one("SELECT preferences FROM users WHERE id = $1", user_id)
    if user["preferences"]:
        for k, v in user["preferences"].items():
            if k == "risk_tolerance":
                # risk_tolerance → AVOIDS new energy 等映射
                ...
    
    # 3. Tushare hierarchy → BELONGS_TO structural edges (一次性，全用户共享)
    if not await pg.fetchval("""
        SELECT EXISTS (
          SELECT 1 FROM chat_memory_edges WHERE rel_type = 'BELONGS_TO' LIMIT 1
        )
    """):
        await seed_industry_hierarchy()  # cold seed Tushare 全 A 股 industry tree
```

### 幂等保证

- 跑过的用户跳过（检查 cold_start_seed episode 存在）
- 行业 hierarchy 一次性 seed（全用户共享）
- 失败可重试（按 source_episode_id 找 seed edge 删后重跑）

---

## § 9 /memory Page UI

### 路由集成

加 `/memory` 进 dashboard sidebar，跟 `/chat` / `/research` / `/portfolio` 平级。

### 3 视图设计

#### 视图 1: Graph viz（Cytoscape.js）
- 节点：圆 + entity_type 颜色
- 边：箭头 + rel_type 标签 + bi-temporal 状态（实线 = current, 虚线 = ended, 灰 = invalidated）
- 交互：拖拽 / 缩放 / hover 看 properties / 点击展开 fact 详情面板
- 数据接口：`GET /api/memory/graph?user_id=X` 返 nodes + edges JSON

#### 视图 2: Timeline view
- 横轴：时间线（valid_from 排序）
- 每条 edge 是一条 horizontal bar (valid_from → valid_to or now)
- 颜色：rel_type 区分
- 用例：看用户对某股观点演化轨迹（"2024-08 重仓茅台 → 2025-03 卖出 → 2025-09 重买"）
- 数据接口：`GET /api/memory/timeline?user_id=X&entity_label=茅台`

#### 视图 3: Audit log
- 列 `invalidated_at IS NOT NULL` 的 facts
- 显示：invalidated_at + 原 fact + invalidated_by（哪条新 fact 触发的）
- 用例：查"系统记错过什么 + 何时纠正"
- 数据接口：`GET /api/memory/audit?user_id=X`

### 实现方式

- **Frontend**: 复用 PR #39 AppShell + Sidebar；新建 `pages/memory/` 目录含 GraphView / TimelineView / AuditView
- **Cytoscape.js** 选型理由：~10K GitHub stars，工业 open-source 主流，跟 React 集成有 react-cytoscapejs 库
- **Read-only 起步**：edit / delete 留 v1.x 后期（涉及 cascade invalidation 复杂度）

### 工程量

3-4 天：
- Backend API 3 接口：1 天
- 3 视图前端：2-3 天
- 测试 + polish：0.5-1 天

---

## § 10 Eval Pipeline

### 3 个核心 metric

#### Metric 1: Recall Precision
**定义**：给定 query，archival_memory_search 返回 k 条 facts 中，真正"相关"的比例。

**实现**：LLM-judge（haiku / 4o-mini）

```python
def recall_precision(golden_query, retrieved_facts, expected_facts):
    """
    For each retrieved fact, judge if it's relevant to golden_query.
    Return precision = relevant_count / total_retrieved
    """
    relevant = 0
    for fact in retrieved_facts:
        judgment = await llm_judge.eval(
            query=golden_query,
            fact=fact,
            prompt="Is this fact relevant to the query? yes/no"
        )
        if judgment == "yes":
            relevant += 1
    return relevant / len(retrieved_facts)
```

**目标**：≥ 0.7 (top-5 中至少 3.5 条真相关)

#### Metric 2: Temporal Correctness
**定义**：给定带时间区间的 query，回答里引用的 fact 跟 valid_from/valid_to 是否对得上。

**实现**：确定性 check（不用 LLM）

```python
def temporal_correctness(golden_query, retrieved_facts):
    """
    golden_query 含 expected_time_range = (start, end)
    检查每条 retrieved_fact 的 valid_from ≤ end AND (valid_to IS NULL OR valid_to ≥ start)
    """
    correct = 0
    for fact in retrieved_facts:
        if fact_overlaps_range(fact, golden_query.time_range):
            correct += 1
    return correct / len(retrieved_facts)
```

**目标**：≥ 0.95 (近完美，因为是确定性 check)

#### Metric 3: Faithful Answer
**定义**：agent 最终回答里每个 claim 是否能 trace 回 retrieved fact（不是 hallucinate）。

**实现**：LLM-judge

```python
def faithful_answer(agent_answer, retrieved_facts):
    """
    Decompose agent_answer into claims.
    For each claim, check if it's grounded in retrieved_facts.
    """
    claims = await decompose_to_claims(agent_answer)
    grounded = 0
    for claim in claims:
        if await is_grounded(claim, retrieved_facts):
            grounded += 1
    return grounded / len(claims)
```

**目标**：≥ 0.85

### 50 Golden Case 集

```jsonl
{
  "query": "我对茅台的看法",
  "expected_facts": ["edge_id_pattern: HOLDS Stock 600519.SH", 
                      "edge_id_pattern: EXPRESSED_VIEW Stock 600519.SH"],
  "expected_tools": ["archival_memory_search"],
  "expected_time_range": null,
  "expected_answer_skeleton": "提到 cash flow + 白酒赛道 + 重仓表态"
}
{
  "query": "跟我持仓相关的白酒股",
  "expected_facts": ["any HOLDS Stock 茅台", "any HOLDS Stock 五粮液"],
  "expected_tools": ["archival_memory_traverse"],
  "expected_traverse_args": {"start_label": "User", "hops": 2, "rel_types": ["HOLDS","BELONGS_TO"]},
  ...
}
...
```

### Tool Routing Accuracy

```python
def routing_accuracy(golden_cases):
    correct = 0
    for case in golden_cases:
        plan = await chat_planner.plan(case["query"])
        actual_tools = [tc.tool_name for tc in plan.tool_calls]
        if set(case["expected_tools"]).issubset(actual_tools):
            correct += 1
    return correct / len(golden_cases)
```

**目标**：≥ 0.85（PR #39 plan_id router 同标准）

### 跑频次

- 每次 prompt 改动 / ontology 变 → 必跑
- 每周 nightly → 必跑
- merge 前 PR gate（routing accuracy < 0.85 不许 merge）

### 实施

新加 `backend/tests/eval/c5_memory_eval.py`，类比 PR #39 `extraction_quality_eval.py`。

50 golden case 文件：`backend/tests/fixtures/eval/c5_memory_golden.jsonl`

工程量：3 天（含 50 case 编写）。

---

## § 11 工业难题撞实表（16 个）

每条带 paper / 产品 ref + 我们方案 + 验证方式。

### 13 通用难题

| # | 难题 | 工业 ref | 我们方案 | 验证 |
|---|---|---|---|---|
| 1 | Write trigger | Letta / mem0 / ChatGPT | Path A agent + Path B 兜底批 | L1 test 双路径 |
| 2 | Granularity | Letta passage / mem0 facts | Edge-level fact + entity-anchor expansion | L0 schema test |
| 3 | Retrieval timing | Letta tool / Anthropic auto | Session-start auto + on-demand tool | L2 cassette |
| 4 | Ranking | RankGPT / RAGAS | RRF fusion 三路 (k=60) | Eval Recall Precision ≥ 0.7 |
| 5 | Conflict resolution | mem0 LLM-judge / Zep bi-temporal | bi-temporal + 4-action LLM-judge | L1 test 4 action + bi-temporal differential test |
| 6 | Eviction | LRU / time decay | Partial index + audit query + manual cli purge | Audit query 周报 |
| 7 | Budget paging | MemGPT 论文核心 | Working memory 自动 archive oldest | L0 test paging logic |
| 8 | User control | ChatGPT / Anthropic Memory | /memory UI viz + audit log（v1.x edit）| Manual dogfood |
| 9 | Faithful recall | Self-RAG / Chain of Note | source_episode_id 强 FK + Eval Faithful Answer | Eval ≥ 0.85 |
| 10 | Provenance | Anthropic Citations API | NOT NULL + FK constraint | L0 schema test |
| 11 | Cross-user pollution | 多租户基本要求 | user_id 全 query 隔离 | L1 test 多用户 |
| 12 | Cold start | UX paper | 从 position + users.preferences seed | L1 test cold seed |
| 13 | Injection prompt-eng | Anthropic system / Letta core block | persona auto-populate at session start | L2 cassette |

### 3 个 Zep 特有

| # | 难题 | 工业 ref | 我们方案 | 验证 |
|---|---|---|---|---|
| Zep-1 | Entity disambiguation | Tushare / 申万 registry | Normalize via registry，failed 时 audit flag | L0 normalize test |
| Zep-2 | Ontology drift | LangChain LLMGraphTransformer best practice | TEXT 字段 + 周 audit query 检测 | Audit query 周报 |
| Zep-3 | Bi-temporal model | Snodgrass 1993 / Zep 2025 | 4 timestamps，区分 valid_to vs invalidated_at | bi-temporal differential test |

每条 spec 里独立段落展开，简历叙事 16 条独立讲点。

### 4 个规模化补丁（百万用户场景）

⚠️ **本节定位**：上面 16 条解法在 dogfood / 千用户级别足够。一旦规模化到百万用户 / 千万 episode / 天，要补这 4 条。每条独立成 milestone（不阻塞 v1.x ship，但是简历讲故事和面试答"工业级产品思维"的关键）。

**为啥单列**：诚实承认 spec 主体是 dogfood 级设计，工业产品先 ship 再 scale，不预先猜测；4 条每条都是独立的 system design 答题点；工程量独立估算 +15-20 天，不阻塞 ship。

| # | 规模化难题 | spec 主体缺口 | 补丁分层（按上线顺序）| 验证目标 |
|---|---|---|---|---|
| Scale-1 | **写入成本规模化** | 单 session $0.005 在百万用户 / 千万 episode / 天 ≈ $50K/天，老板会问 | (a) **写入分级**：importance ≥ 0.9 走中模型 + 数值正则双校验 / 中信号走 Haiku 4.5 / 低信号纯规则 (b) **前置过滤升级**：现在的"关键词 + 长度"是规则版，规模化时上 200M 参数本地小分类器（1ms 推理）再砍 50% (c) **离线 + 流式分离**：用户主路径只做"原文落库 + 标记待抽"，抽取全部丢后台批，每小时跑一次 (d) **滥用保护**：每用户每小时 memory 写入次数限额 | 单租户 P95 主路径写入 < 100ms / 后台抽取吞吐 ≥ 1 万 episode/分钟 / cost per 千 episode ≤ $1 |
| Scale-2 | **累积抽取错误（图卫生）** | normalize 失败 audit + provenance 是被动机制，没有主动巡检，错误会污染检索 | (a) **重要 edge 双层校验**：importance ≥ 0.9 走"小模型抽 + 中模型 verify + 数值正则"，三关不通过留 staging 表不进图 (b) **用户回路 first-class**：/memory page "一键否决"按钮做核心 UX 不是隐藏功能；每周邮件推"我们记的关于您最新 5 件事，请确认"（金融审计路径常态化） (c) **图卫生定期巡检**：每月后台 job 统计哪些 prompt pattern 产出 edge 频繁被 invalidated → 反馈调 prompt（Zep-2 的 audit query 升级为 SOP）| invalidation rate < 5%（dogfood baseline）/ 用户主动否决率 < 2% / prompt 调优 release ≥ 月度 |
| Scale-3 | **调试可解释性 + 上线安全** | provenance FK + /memory UI 是"事后"机制，缺"全链路 trace"和"上线 dual-write" | (a) **统一 request_id 全链路**：用户提问 → 检索 query → 命中 edge → 原始 episode → LLM 输入输出，全部一个 ID 串到一张 observability 表，客服 30 秒定位（PR #39 已有 trace 框架，扩展）(b) **dual-write 1-2 月**：v0.9 in-session memory 和 v1.x archival 并行跑，每天 diff 检查同问题答案一致性，差异自动入 eval 集 (c) **三层指标进监控大盘**：检索路由准确率 ≥ 0.85 / 抽取召回 F1 ≥ 0.7（每周 50 条人工标）/ 端到端回答正确率（v0.8.5 LLM-judge）— 单层退化告警 | dual-write diff < 10% / 大盘三层指标 ≥ baseline / SOP "客诉 → 30 秒定位 → 1 小时复现"演练通过 |
| Scale-4 | **多租户 + 规模化隐形成本** | 只有 user_id 第一字段 + 索引，单 PG 单 AGE 图全用户共享，撑不到 50 万用户 | (a) **分库分表**：user_id hash 取模分 N 个 PG schema，每 schema 独立 AGE 图实例 — 牺牲跨用户全局查询（金融助手用不到），换每 schema ≤ 2000 万行 edge (b) **Milvus 按 user 分区**：partition by user_id，检索时 partition pruning 避免全 collection 扫 (c) **冷热分离**：90 天前 edge 走 PG 分区表（按 recorded_at 分），冷数据归档到压缩分区 (d) **GDPR / 用户删除**：`DELETE WHERE user_id = $1` 后台 job 异步执行，Milvus 同步 `delete_by_filter`，审计日志保留删除时间戳 (e) **监控指标**：每用户 edge 数 P95 / 单用户检索 P99 / 分区倾斜度，超阈值告警 | 单 schema ≤ 2000 万 edge / Milvus partition pruning 命中 ≥ 90% / 99% 检索只扫近 90 天热数据 / GDPR 删除 SLA ≤ 24h |

### 规模化补丁的触发上线条件

不是 v1.x ship 时全做，按真实流量触发：

- **Scale-1 触发**：日活 > 1 万 或 月成本 > $1K
- **Scale-2 触发**：dogfood 1 月后 invalidation rate > 5% 或用户报错
- **Scale-3 触发**：第一次客诉 "答错了为啥" 30 分钟内定位不到
- **Scale-4 触发**：注册用户 > 10 万 或 单库 edge > 5000 万行

### 简历叙事维度

16 工业难题 = 算法 / 系统设计深度（"我撞实了 16 个"）。
4 规模化补丁 = 工业产品思维（"我懂从 dogfood 到百万用户的差距"）。**面试官常问的"上量后会遇到啥"答的就是这 4 条。**

### 8 条算法深度 + 工程细节难题

⚠️ **本节定位**：spec 主体 16 条覆盖 baseline，§ 11 4 条规模化补丁覆盖上量场景。这 8 条是"算法深度 + 工程细节 + 安全 / UX 完整度"层，**dogfood 期就可能撞**（不像规模化补丁要等上量），按"v1.x ship 必做（6 条）/ 触发后做（2 条）"分组。

#### 优先级分组

| 类别 | v1.x ship 必做（6 条）| 触发后做（2 条）|
|---|---|---|
| 算法 | #2 投毒 + Agent 幻觉写 / #3 importance + 时间感知 / #4 跨轮抽取 | #1 向量模型升级（qwen v3→v4 时触发）|
| 工程 | #5 3 方一致性反向失败 / #7 Memory vs KB routing | #6 Ontology 演化（加新 type 时触发）|
| 业务 | #8 用户心智模型 + 信任 | — |

#### 8 条详表

| # | 难题 | spec 主体缺口 | 补丁 | 验证 |
|---|---|---|---|---|
| 1 | **向量模型升级迁移** | § 4 优化只写 embedding cache，无升级期 dual-write / 维度不同 / alias 切换 | (a) Milvus alias 模式：`current_alias` 指向真 collection，升级时建新 collection 重算，alias 原子切换 (b) `embedding_version` 字段标记每条向量的模型版本 (c) 重算期 dual-write，检索按 alias 取当前版本 | 切换演练：N 万向量 dual-write 1 小时无错 / alias 切换零 downtime / 老版本可回滚 |
| 2 | **Memory 投毒 + Agent 幻觉写入** | § 4 写入 pipeline 假设 episode 内容可信，无 prompt injection 检测，无 agent 写入审计 | (a) 写入前过 prompt-injection 分类器（小模型 + 关键词组合），命中标 `audit_flag='suspicious'` 不进 archival，走人工 review (b) Agent 调 `archival_memory_insert` 必须带 `evidence_quote`，必须能在 episode 原文 substring 找到的引用，找不到拒绝写 (c) 监控：每用户每周新写入 / 老 edge 比例突然飙高 → 告警 | L1 投毒攻击测试集（30 个已知 prompt injection pattern）/ agent evidence_quote 命中率 ≥ 0.95 / 监控告警演练 |
| 3 | **Importance 不稳 + 最近偏置（时间感知 ranking）** | importance 连续值 LLM 标不稳 / RRF 公式 `Σ 1/(60+rank)` 不带 importance 加权 / 不带时间衰减 → 长尾老 edge 沉底 | (a) **importance 离散三档** `{high=0.9, medium=0.5, low=0.2}`，LLM 标离散更稳定，cost 不变 (b) **后验行为信号校准**：周 job 根据"被 retrieve 命中数 + 用户否决"反向调 importance，行为信号比 LLM 自评准 (c) **RRF 加 importance 加权 + 时间感知**：`score_final = (Σ 1/(60+rank)) × importance_weight × time_decay`（详见下方 #3 公式展开）(d) **τ 按 rel_type 分级**：τ_持仓（HOLDS/SOLD）=365d / τ_偏好（PREFERS/AVOIDS/WATCHES）=180d / τ_观点（EXPRESSED_VIEW/STUDIED）=90d — 金融市场观点 3-6 月过时，持仓事实可更长 (e) 长尾召回监控（eval pipeline sample 100 query，top-5 valid_from P90 不能全集中近 7 天）| 离散三档 importance 跨 session 一致性 ≥ 0.9 / RRF v2 加时间感知前后 long-tail recall 提升 ≥ 15% / 长尾召回监控周报上大盘 |
| 4 | **跨轮关系抽取** | episode 单元粒度死板，完整 fact 跨 3 turn 抽不出（"我刚买了" → "买了什么" → "茅台 500 股"）| (a) End-of-session 兜底批扫时按"语义连续性"合并相邻 episodes（关键词共指 + 时间间隔 < 5 分钟）(b) 抽取 prompt 输入升级为"最近 5 turn 滑动窗口"而非单 turn (c) L1 测试新增"跨 turn fact 完整性测试" | 跨 turn fact 抽取召回 ≥ 0.7 / 单 turn fact 抽取召回不退化 |
| 5 | **PG + AGE + Milvus 三方一致性反向失败** | § 4 Step 7 outbox 只覆盖 Milvus 单向失败，反向（AGE 成功 PG rollback / 进程崩溃在 Step 8 之前 → 重复抽）未覆盖 | (a) AGE 同步必须在 PG 同事务（spec 已写，补 verify 测试）(b) **幂等键 UNIQUE constraint** `(episode_id, source_label, target_label, rel_type, valid_from)` 防重复抽 (c) 进程崩溃恢复 job：启动时扫"PG 写完 + Milvus pending + episode `extracted_at IS NULL`"的 inconsistent 状态做 reconciliation | L2 chaos test：抽取 pipeline 中途 kill 进程，重启后 episode 不重复抽 / 不留孤儿 AGE 节点 |
| 6 | **Ontology / Schema 演化迁移** | § 3 "drift-tolerant" 只允许新词进 properties，无新 entity_type 上线时回填老边的 migration 框架 | (a) `ontology_version` 字段落每条 edge (b) 上新 type 时跑 data migration job：扫所有老 edge properties，LLM 重判是否归入新 type (c) migration 输出 diff 让作者 review，不自动 apply — "data migration job"，类似 Alembic 但跑数据 | v1.x 试做一次 "Bond 加入 ontology" 的 data migration 演练 / migration diff 准确率 ≥ 0.9 |
| 7 | **Memory vs KB Search 检索路由** | v0.7 KB Search 已有 / C.5 上 archival memory / spec § 6 routing 只在 memory 内部 6 tool / memory 整体 vs KB 整体 routing 没写 → 用户问"基于持仓推荐"agent 不知道走哪 | (a) **LangGraph supervisor 加 router 节点** 输出 `retrieval_targets: ["memory" / "kb" / "both"]` (b) 触发词区分：memory（"我 / 我的 / 上次 / 持仓 / 偏好"）/ KB（"研报 / 财报 / 公告 / 政策"）/ both（"基于我 + 推荐 / 结合 + 我的"）(c) 两路结果 prompt 显式区隔：`[用户上下文]`（memory）vs `[市场知识]`（KB），让 LLM 不混淆个人事实和公开知识 (d) 默认 fallback memory（个人化场景多）| Routing eval 50 case ≥ 0.85 / both 类 query LLM 不矛盾化（用户偏好 vs 市场跑输应该是 trade-off 不是矛盾）|
| 8 | **用户心智模型 + 信任危机** | § 9 /memory page 是被动 UI（用户主动来才看到），无主动告知机制 → 上线第一周用户问"你怎么监视我" | (a) Agent 在 chat 内**显式提及来源**："基于您 2024-11 提过的偏好（[查看](#mem-id)）..." 让用户感知 memory 在用 (b) 首次 session 强 onboarding 弹窗："我会记住您的投资偏好和持仓，可随时在 /memory 删除" (c) 每月推一封"我们记得关于您的 5 件事，请确认"邮件（也是 § 11 Scale-2 图卫生 hook）| 用户调研 5 人：首次 session 后 4/5 知道有 memory 系统 / 月度确认邮件打开率 ≥ 30% |

#### #3 时间感知 RRF 公式展开（替换 § 5 现有 RRF）

跟 § 5 现有 RRF（`score = Σ 1/(60+rank_in_retr)`）兼容，在 fusion 后再乘两个因子：

```python
def reciprocal_rank_fusion_v2(retriever_results, edges_meta, k=60, top=5):
    rrf_scores = defaultdict(float)
    for retriever_list in retriever_results:
        for rank, item in enumerate(retriever_list, start=1):
            rrf_scores[item["edge_id"]] += 1.0 / (k + rank)
    
    final_scores = {}
    now = datetime.utcnow()
    for eid, base in rrf_scores.items():
        meta = edges_meta[eid]
        # importance 三档映射，low 不完全压制(下限 0.6)
        imp_weight = {0.9: 0.95, 0.5: 0.75, 0.2: 0.6}.get(meta["importance"], 0.75)
        # 时间衰减按 rel_type 分级 τ
        tau_days = {
            "HOLDS": 365, "SOLD": 365,
            "PREFERS": 180, "AVOIDS": 180, "WATCHES": 180,
            "EXPRESSED_VIEW": 90, "STUDIED": 90,
        }.get(meta["rel_type"], 180)
        # 历史 edge (valid_to IS NOT NULL) 取 max(valid_from, valid_to) 作为参考时间
        ref_time = meta["valid_to"] or meta["valid_from"]
        delta_days = (now - ref_time).days
        # 衰减底 0.5 不消失 — 老 fact 仍可被检索，保 audit / 长尾价值
        time_decay = 0.5 + 0.5 * math.exp(-delta_days / tau_days)
        final_scores[eid] = base * imp_weight * time_decay
    
    return sorted_top_k(final_scores, top)
```

**关键设计取舍**：
- **衰减底 0.5 不为 0**：防止老 fact 完全消失。1 年前用户说"我永不碰科技"仍要可被召回，只是排名靠后
- **importance 下限 0.6**：low importance 不被完全压制（0.6 vs 0.95 = 36% 差距，有区分度但不一边倒）
- **τ 按 rel_type 分级**：金融垂直洞察 — 持仓事实（365d）> 偏好（180d）> 观点（90d），工业 ranking 系统通用 lifecycle 思路
- **历史 edge 用 valid_to 衰减**：事实"最近一次为真的时间"作参考 — 用户 2024-08 买 2025-03 卖的茅台，从 2025-03 起开始衰减，不是从 2024-08
- **后验校准 importance**：LLM 一次抽完不动，周 job 再调一次，行为信号比 LLM 自评稳定 — 类似 YouTube / TikTok ranking 系统的"prediction + posterior calibration"

#### 简历讲点（8 条）

跟 16 + 4 三层叠加（总 28 条独立讲点）：
- **第 1 层 16 条** = 算法 / 系统设计 baseline
- **第 2 层 4 条 Scale-X** = 工业产品思维（上量后）
- **第 3 层 8 条** = 算法深度 + 工程细节 + 安全 / UX

简历讲法：

> "我没只做工业 baseline。从 dogfood 期就把投毒 + Agent 幻觉写 / 三方一致性 / Memory vs KB routing / 时间感知 ranking（RRF + importance 三档 + τ 按 rel_type 分级 + 后验行为校准）这些工业系统真实痛点纳入 spec，撞实并落代码。"

#### 工程量增量

**v1.x ship 必做 6 条 +5-7 天**（已加进 § 13 主表）：

| # | 补丁 | 天 |
|---|---|---|
| #2 | 投毒 + Agent 幻觉（分类器 + evidence_quote 校验 + 监控）| 1.5 |
| #3 | importance 三档 + 时间感知 RRF + τ 配置 + 长尾监控 | 1.5 |
| #4 | 跨轮抽取（5 turn 滑动窗口 + 测试）| 1 |
| #5 | 三方一致性（幂等键 + 崩溃恢复 job）| 1 |
| #7 | Memory vs KB routing（supervisor router + prompt 区隔 + eval）| 1 |
| #8 | 用户心智（显式提及 + onboarding + 邮件 spec）| 0.5 |
| **小计** | | **6.5** |

**触发后做 2 条**（进 § 14 P3 hooks）：
- #1 向量模型升级 — qwen v3→v4 时触发
- #6 Ontology 演化 — 加新 entity_type / rel_type 时触发

---

## § 12 Test Strategy

跟 PR #39 同 framework，加 bi-temporal differential test。

### L0 Unit

- Pydantic schema validation（entity / edge / tool args）
- Pure function：RRF fusion / token counter / persona format / entity normalizer
- Conflict resolution 4-action 决策（LLM mock）

### L1 Integration

- Mock LLM 测 extraction → conflict → upsert 端到端
- 6 MCP tool 单测
- Cold start populator
- Working memory auto-paging

### L2 Cassette

- 真 LLM 录 cassette 测 archival_memory_search / traverse / recall full path
- 跟 PR #39 cassette framework 复用

### Bi-temporal Differential Test（新）

模拟用户 5 个 session 序列（持仓演化），断言每个时间点 graph 状态正确。

```python
@pytest.mark.differential
async def test_bi_temporal_holding_evolution():
    user_id = create_test_user()
    
    # Session 1 (2024-08): 重仓茅台 500
    await simulate_chat(user_id, "我重仓了茅台 500 股", date="2024-08-01")
    assert holds(user_id, "600519.SH").qty == 500
    assert holds(user_id, "600519.SH").valid_to is None
    
    # Session 2 (2025-03): 加仓
    await simulate_chat(user_id, "茅台又加了 200 股", date="2025-03-15")
    edges = all_holds_edges(user_id, "600519.SH")
    assert len(edges) == 2  # 老 edge valid_to set + 新 edge
    
    # Session 3 (2025-06): 卖出
    await simulate_chat(user_id, "茅台清了", date="2025-06-01")
    assert holds(user_id, "600519.SH", valid_to_null=True) is None
    sold_edges = sold_edges_for(user_id, "600519.SH")
    assert len(sold_edges) == 1
    
    # Session 4 (2025-12): 用户澄清记错
    await simulate_chat(user_id, "其实我说错了，去年那 500 股是五粮液", date="2025-12-01")
    invalidated = invalidated_edges(user_id)
    assert len(invalidated) >= 2  # 原 HOLDS 茅台 edges 被 invalidated
    holds_wuliangye = holds(user_id, "000858.SZ")
    assert holds_wuliangye is not None
    
    # Session 5 (2026-01): 重新建仓茅台
    await simulate_chat(user_id, "现在又看好茅台了，建仓 100 股", date="2026-01-15")
    current_holds = holds(user_id, "600519.SH")
    assert current_holds.qty == 100 and current_holds.valid_to is None
```

### L3 Dogfood

作者真实跑 ≥ 10 chat 验证 user-perceived quality。

### 工程量

5 天：L0 1 天 + L1 1.5 天 + L2 1 天 + bi-temporal differential 1.5 天

### 复用基建

- PR #39 mock_llm_client + cassette 框架 + AsyncPostgresSaver fixture
- v1.0 监控引擎 Celery worker subprocess fixture（async extraction batch 测试）

---

## § 13 工程量估算

| 模块 | 天 |
|---|---|
| Schema + AGE setup + Tushare/申万 registry cold seed | 3 |
| HierarchicalMemory class + 6 MCP tool | 4 |
| 写入 pipeline (extraction + conflict + AGE/Milvus sync + outbox) | 5 |
| **Cost optimization layer (5 项 ladder)** | **5** |
| 读取 pipeline (3-way hybrid + RRF) | 4 |
| Working memory + auto-injection + cold start populator | 3 |
| /memory UI (Cytoscape + 3 视图) | 4 |
| Eval pipeline (3 metric + 50 golden + routing accuracy) | 3 |
| Tests (L0 + L1 + L2 + bi-temporal differential) | 5 |
| Spec / plan / docs | 2 |
| **算法深度 + 工程细节 6 条 v1.x 必做（§ 11 末尾详表）** | **6.5** |
| **Total** | **44.5**（max scenario）/ **36.5**（smooth scenario）|

> **注 1**：以上 36.5-44.5 天 = 30-38 天 dogfood baseline + 6.5 天算法深度补丁（§ 11 末尾 8 条中 v1.x 必做的 6 条 — 投毒检测 / 时间感知 RRF / 跨轮抽取 / 三方一致性 / Memory-vs-KB routing / 用户心智）。
>
> **注 2**：**§ 11 4 条规模化补丁（Scale-1 ~ Scale-4）独立 +15-20 天 milestone**，不阻塞 v1.x ship，按 § 11 的"触发上线条件"分批做。
>
> **注 3**：§ 11 末尾 8 条中**触发后做的 2 条**（#1 向量模型升级 / #6 Ontology 演化）进 § 14 P3 hooks，触发后才上工。

跟 v1.0 监控引擎实际 ship（~25 天）比 ×1.2-1.5 量级，跟 PR #39 (~80+ task autonomous pipeline) 比小 1/2。

适合走 PR #39 同款 autonomous overnight pipeline 模式（spec → 5-7 plan → autonomous agent execute → manual followup cassette + dogfood）。

---

## § 14 v1.x Ship Checklist + P3 Hooks

### v1.x ship 完整 checklist

#### 后端
- [ ] `chat_memory_episodes / nodes / edges / working_blocks` 4 PG 表 + 索引 ship
- [ ] AGE 扩展加载 + 'chat_memory' 图 + 7 vlabel + 11 elabel ship
- [ ] Milvus `chat_memory_edge_embeddings` collection ship
- [ ] HierarchicalMemory class impl + Memory protocol DI 切换 in chat agent
- [ ] 6 MCP tool 接入 `mcp_servers.yaml` 独立 `memory` profile
- [ ] 写入 pipeline 8 step + 4-action conflict resolution
- [ ] 读取 pipeline 3-way hybrid + RRF + working memory auto-injection
- [ ] Cold start populator (3 路 seed + 幂等)
- [ ] Cost optimization 5 项启用 (prompt cache + batch + skip gate + async + embedding cache)
- [ ] outbox pattern for Milvus + 后台 retry job

#### 前端
- [ ] `/memory` 路由进 sidebar
- [ ] Graph viz (Cytoscape.js)
- [ ] Timeline view
- [ ] Audit log view
- [ ] 3 个 backend API endpoint (graph / timeline / audit)

#### Eval
- [ ] 50 golden case `c5_memory_golden.jsonl`
- [ ] 3 metric impl (Recall Precision / Temporal Correctness / Faithful Answer)
- [ ] Tool routing accuracy ≥ 0.85
- [ ] Cost / session ≤ $0.005

#### Tests
- [ ] L0 unit (schema + RRF + paging logic)
- [ ] L1 integration (extraction + conflict + 6 tool)
- [ ] L2 cassette (search / traverse / recall full path)
- [ ] **Bi-temporal differential test (5 session 序列)**
- [ ] L3 dogfood ≥ 10 chat 真实验证

#### Docs
- [ ] `docs/claude-context/c5-cross-session-memory-done.md` 知识卡 ship 完
- [ ] CLAUDE.md 加索引
- [ ] 16 工业难题撞实表完整 spec 化（每条 paper ref + 方案 + 验证）

### Manual Followup（不阻塞 ship）

- 真 LLM cassette 录制（5 个 representative scenarios）
- Playwright e2e (chat-with-memory + /memory UI 交互)
- 作者 dogfood 周报：fact 累积 / search hit rate / cost 实测

### P3 留 Hook（v1.x 后期 / v2）

#### 规模化补丁 4 条（§ 11 4 条 Scale-X 的 hook，按 § 11 触发条件上线）

- [ ] **Scale-1 写入分级 + 前置过滤升级 + 离线 batch 流式化**（importance-based 模型路由 / 200M 本地小分类器 / 主路径只落库异步抽 / per-user rate limit）
- [ ] **Scale-2 图卫生 + 用户回路 first-class**（重要 edge 双层校验 + 数值正则 / /memory 一键否决 UX 进核心 / 月度 prompt 巡检 SOP / 周邮件用户确认）
- [ ] **Scale-3 全链路 trace + dual-write + 三层监控大盘**（request_id 串全链路 / 1-2 月 in-session 与 archival dual-write diff / 检索 / 抽取 / 回答三层指标进大盘 + 单层退化告警）
- [ ] **Scale-4 分库分表 + Milvus 分区 + 冷热分离 + GDPR pipeline**（user_id hash 分 N schema / Milvus partition by user_id / 90 天 PG 分区表归档冷数据 / 用户删除后台 job + 审计日志）

#### 算法深度 hook 2 条（§ 11 末尾 8 条中触发后做的）

- [ ] **#1 向量模型升级迁移**（Milvus alias 模式 + `embedding_version` 字段 + dual-write 期检索一致性 + 老版本回滚）— qwen v3→v4 或同维度模型对比时触发
- [ ] **#6 Ontology / Schema 演化迁移**（`ontology_version` 字段 + LLM 重判老 edge type + diff review 不自动 apply）— 加新 entity_type（如 Bond）或 rel_type（如 HEDGES）时触发

#### 产品功能 hook

- [ ] /memory UI edit & delete (含 cascade invalidation 复杂度)
- [ ] 跨用户 memory sharing (团队共享 memory)
- [ ] Memory replay (LLM-as-time-machine：用某天 graph 重放 chat)
- [ ] 跨 chat thread fact merging (chat A 提的 fact 跟 chat B 自动 link)
- [ ] Memory privacy controls (per-fact visibility / 加密)
- [ ] Tier 2 加 node embedding collection（如 dogfood 发现 entity-anchor 召回不够）
- [ ] Conflict resolution 升级：考虑 LLM-judge 错误率，加 human-in-the-loop 选项
- [ ] Memory decay：长期不被 retrieve 的 fact 自动 archive 到 cold tier (S3-like)

---

## § 15 简历叙事段（写作品集时直接抄）

C.5 ship 完后,可以这样讲:

> "C.5 cross-session memory 撞实 16 个工业难题 (13 通用 + 3 Zep 特有)。架构是 Letta MemGPT 论文 (2023) 的 agent-self-managed tool 接口 + Zep / Graphiti 论文 (Jan 2025) 的 temporal knowledge graph 后端 杂交版,加 mem0 风的 LLM-judge conflict resolution + Anthropic Citations API 风的 provenance FK。Storage 选 PG + Apache AGE 不上 Neo4j —— 复用 v1.0 PG 基建,运维一致,但 PG 表存全数据 + B-tree 索引 / AGE 镜像存图拓扑给 Cypher 用,避开 AGE agtype 索引能力弱的问题。Bi-temporal model (Snodgrass 1993) 区分 real-world validity vs transaction time,让'用户对茅台态度演化'这类金融 use case 关键 query 表达力完整。3-way hybrid retrieval (BM25 + vector + graph) + RRF fusion 是 2024-2025 工业前沿 (Microsoft GraphRAG paper)。Cost optimization 5 项 ladder (prompt cache + batch + skip gate + async + embedding cache) 把单 session 成本从 $0.025 降到 $0.005,接近 mem0 paper 报告的 $0.001。"

### 面试场景叙事段（"工业级产品思维"维度）

被问到"你这个 dogfood 项目怎么扩到百万用户"时:

> "Spec 主体是 dogfood / 千用户级落地,30-38 天 ship。但我在 spec § 11 末尾显式列了 4 条规模化补丁 (Scale-1 ~ Scale-4),每条带触发上线条件、补丁分层、验证目标 —— 不预先做、不假装支持、不阻塞 ship。
> 
> Scale-1 写入成本规模化:把 spec 主体的 5 项省钱组合拳从单用户视角扩到百万用户,加写入分级 (importance ≥ 0.9 走中模型 + 数值正则,中信号 Haiku,低信号纯规则) + 200M 参数本地小分类器替代规则版前置过滤 + 主路径只落库异步抽 + per-user rate limit。
> 
> Scale-2 累积抽取错误:重要 edge 走"小模型抽 + 中模型 verify + 数值正则"三关 + /memory page 一键否决做核心 UX (不是隐藏功能) + 月度 prompt 巡检 SOP。**这是工业产品和纯 ML 项目的分水岭 —— 不指望 LLM 100% 对,指望系统让用户花 10 秒就能纠正。**
> 
> Scale-3 调试 + 上线安全:request_id 全链路串到 observability 表 (PR #39 trace 框架扩展) + v0.9 in-session 和 v1.x archival dual-write 1-2 月 diff 检查 + 三层指标进监控大盘 (路由准确率 / 抽取召回 F1 / 端到端正确率)。
> 
> Scale-4 多租户 + 规模化:user_id hash 分 N 个 PG schema (每 schema ≤ 2000 万 edge) + Milvus partition by user_id (检索时 partition pruning) + 90 天 PG 分区表冷热分离 + GDPR 删除走后台 job (`DELETE WHERE user_id` 不进主路径)。
> 
> 工程量这 4 条单独 +15-20 天独立 milestone,按真实流量触发分批做。Spec 主体 30-38 天先 ship,等 dogfood / 真用户暴露问题再扩。"

### 面试场景叙事段（"算法深度 + 工程细节"维度）

被问到"你 ranking / 安全 / 工程一致性怎么做"时:

> "Spec § 11 末尾我又加了 8 条算法深度 + 工程细节难题,6 条 v1.x 必做 +5-7 天进 spec,2 条触发后做进 P3 hooks。重点几个:
>
> **检索 ranking 不是 RRF 跑完就完事**。原 RRF 公式 `Σ 1/(60+rank)` 不带 importance 加权也不带时间衰减,长尾老 edge 会沉底。我加 RRF v2: `score_final = (Σ 1/(60+rank)) × importance_weight × time_decay`。importance 改三档离散 `{high=0.9, medium=0.5, low=0.2}` 让 LLM 标的更稳,映射到 [0.6, 0.95] 加权(low 不完全压制);time_decay = 0.5 + 0.5×exp(-Δt/τ) 衰减底 0.5 不消失保 audit 价值;**τ 按 rel_type 分级** — 持仓事实(HOLDS/SOLD)τ=365 天,偏好(PREFERS/AVOIDS)τ=180 天,观点(EXPRESSED_VIEW/STUDIED)τ=90 天 — 金融市场观点 3-6 月就过时,持仓事实可更长。importance 还有**后验行为信号校准**周 job(被 retrieve 命中数 + 用户否决) — 类似 YouTube / TikTok 的 "prediction + posterior calibration"。
>
> **Memory 投毒 + Agent 自我幻觉写**(Anthropic 2024 indirect prompt injection paper 真案例):写入前过 prompt-injection 分类器命中 audit_flag 不进图;Agent 调 `archival_memory_insert` 必须带 `evidence_quote`(必须能在 episode 原文 substring 找到的引用),找不到拒绝写。
>
> **PG + AGE + Milvus 三方一致性反向失败**:spec 主体只覆盖 Milvus 单向 outbox,但反向(AGE 成功 PG rollback / 进程崩溃在标记 extracted_at 之前 → 重复抽)我加幂等键 UNIQUE constraint + 启动时 inconsistent 状态 reconciliation job + L2 chaos test。
>
> **Memory vs KB 检索路由**(v0.7 KB Search 已有,C.5 上 archival memory):LangGraph supervisor 加 router 节点输出 `["memory" / "kb" / "both"]`,触发词区分(我 / 我的 → memory,研报 / 财报 → KB,基于我 + 推荐 → both),两路结果 prompt 显式区隔 `[用户上下文]` vs `[市场知识]` 让 LLM 不混。
>
> **跨轮关系抽取**:spec 主体按 episode(单 turn)抽,但'我刚买了' → '买了什么' → '茅台 500 股' 跨 3 turn 单 turn 都抽不出。eos 兜底批扫时按语义连续性合并相邻 episode + 抽取 prompt 升级为 5 turn 滑动窗口。
>
> **用户心智模型 + 信任**:Agent 在 chat 内显式提及 memory 来源(基于您 2024-11 的偏好 [查看](#mem-id))、首次 session onboarding 弹窗、月度'我们记得关于您的 5 件事请确认'邮件 — Apple Intelligence / ChatGPT memory 上线第一周都吃过这个亏。"

---

## 附录

### 附录 A: Metric / Strategy / Concept 白名单（部分）

详见 `backend/app/memory/registry.py`（实施时建）。

### 附录 B: Step 6 Apply Action 详细 SQL

详见 `backend/app/memory/conflict_resolver.py`（实施时建）。

### 附录 C: 6 MCP Tool 完整 Pydantic Schema

详见 `backend/app/mcp_server/tools/memory/*.py`（实施时建）。

### 附录 D: Trigger Words 完整列表

trigger traverse 词清单（system prompt 内）：
- 关系: 相关 / 类似 / 同样 / 同
- 行业: 同行业 / 同赛道 / 同概念 / 所属 / 属于 / 归类
- 拓扑: 之间 / 对比 / vs / 链 / 上下游 / 产业链 / 供应链 / 范围 / 覆盖

---

## 上游 spec / context 引用

- `docs/superpowers/specs/2026-05-09-v0.9-chat-mode-c1c2-design.md` — PR #39 spec § 1.3 决策 3 (D MemGPT 推 C.5)
- `docs/claude-context/v0.9-chat-c1c2-architecture.md` — PR #39 ship summary
- `docs/claude-context/v1.0-monitoring-engine-done.md` — Celery + Redis + PG infra 复用
- `docs/claude-context/optional-extras-for-heavy-deps.md` — AGE / jieba / cytoscape 依赖管理
- `docs/claude-context/test-db-layered-strategy.md` — L0/L1/L2 测试分层
- `docs/claude-context/celery-redis-test-fixture-pattern.md` — async batch 测试 pattern

---

## 决策 anchor（spec 不变）

| 决策 | 选择 | 见 |
|---|---|---|
| 范式 | 杂交 (Letta tool + Zep KG) | § 1 |
| Extraction 触发 | D (agent + 兜底批) | § 4 |
| Graph DB | PG + Apache AGE | § 2 |
| Ontology | Prescribed seed + drift-tolerant | § 3 |
| Milvus collection | 单 collection (edges only) | § 5 |
| Graph traversal | on-demand 单独 tool | § 5 § 6 |
| Tool count | 6 | § 6 |
| 工业难题 | 16 全 surface | § 11 |
| Cost optimization | 5 项 ladder | § 4 |
| **规模化补丁** | **4 条 Scale-X 独立 milestone（不阻塞 ship，按真实流量触发）** | **§ 11 § 14** |
| **算法深度 + 工程细节** | **8 条（v1.x 必做 6 + 触发后 2），含时间感知 RRF + importance 三档 + τ 按 rel_type 分级** | **§ 11 § 5 § 14** |
| 工程量 | 36.5-44.5 天（dogfood + 6 条算法深度），规模化补丁 +15-20 天 / 算法深度 hook 2 条触发后做 | § 13 |
