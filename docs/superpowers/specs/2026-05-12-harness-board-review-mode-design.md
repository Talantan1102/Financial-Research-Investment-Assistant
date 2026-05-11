# Harness Board Review Mode 复合型工具 Design Spec

**作者**:Talantan1102
**起草**:2026-05-12
**状态**:Spec 草稿 → 待 user review → writing-plans
**类型**:Harness Board 扩展,开发者元工具,自用,不进产品

---

## § 0 元信息与范围

本 spec 设计 **Harness Board Review Mode** —— 在 2026-05-07 已 ship 的 Harness Board(D / B / 决策 三 tab + 8 维 + 62 capability + 5 类 derive_rule)上扩充为**复合型项目知识工具**,把 board 从"开发流程管理"单一形态升级为同时承担 4 类复习场景的多视图工具:

| 场景 | 用户原话 | 主要服务视图 |
|---|---|---|
| **A** | 求职 / 面试讲项目(30-60 min 把项目讲清楚) | V4 故事时间线 |
| **B** | 自己跨时间 onboard 自己(几周/月没碰再回来) | V1 网格 + V2 模块深读 |
| **C** | 系统化 vs 模块化双视角切换 | V2 模块深读 + V3 系统鸟瞰 |
| **D** | 主动召回(出题/闪卡/间隔重复) | V5 闪卡 SRS |

**核心心智模型**:复合型工具 = **一个统一底座(DeepCard)+ 5 个视图(V1-V5 投影)**。

新版本 story 不再手工维护(`docs/project-story.md` 410 行已因重构过期),而是**从 DeepCard 集合按叙事弧 render 出来**,代码 / 决策变了 story 自动跟着变。

**前置 spec 引用**:
- `2026-05-07-harness-board-design.md`(底座现状:Starlette + Jinja + sqlite + 5 类 derive_rule)
- `2026-05-07-harness-board-m2-design.md` / `m3-design.md`(decisions tab 设计)
- `2026-05-10-c5-cross-session-memory-design.md`(provenance / evidence_quote 防幻觉机制借鉴)
- `2026-05-05-v0.8.5-constrained-router-design.md`(constrained JSON schema LLM 调用范式)
- `2026-05-02-v0.7-kb-search-milvus-design.md`(Milvus collection 设计范式 + qwen embedding 选型)

**关键 memory 引用**:
- `user_portfolio_target` — 求职定位 LLM 应用算法 + infra
- `feedback_design_doc_format` — 四件套(问题陈述 + 业界 alternatives + tradeoff + 量化评估)
- `feedback_no_portfolio_simplification` — 严谨度不降,但克制范围
- `product-minimalism-default` — 默认走克制版本,v1.x escape hatch 留口
- `feedback_estimate_in_claude_code_walltime` — 工期按 Claude Code wall time + 区分人 bound 段
- `feedback_long_running_task_slot_pipeline` — 长程任务三段式槽位,白天异步不监督需要原料库存
- `feedback_real_collision_not_simulated` — 撞工业界问题前验证两端真实存在
- `project_eval_pipeline_contract` — golden 测试范式
- `kb-embedding-choice` — qwen text-embedding-v3 / 1024d / batch=10
- `c5-plan4-mcp-tools-done`(evidence_quote 校验机制)

**不在范围**(显式排除,§ 12 详述):
- 在 board 中嵌入对话式问答(L3 LLM)— 重复 /chat 端,违背"看板"语义
- 闪卡 LLM 自动评分(L4)— 引入幻觉,SM-2 自评足够
- 闪卡 LLM 出题(L4)— 机械模板派生 2-3 张/卡足够
- FSRS 算法(v1.x 升级)— SM-2 50 行够用
- 跨用户共享 / 多人协作 — 自用工具
- Mobile 端 / 触屏优化 — 桌面 + 大屏复习场景
- 真因果方向图(linked_capabilities 是无向集合,v2 再决)
- 自动 commit-time 提取细化(git log 抓首个 commit,不细究 PR 顺序)

---

## § 1 痛点动机:为什么现在做

### § 1.1 现状痛点

v0.9+ 起项目进入"9 模块并行 + 跨周节奏 + Claude Code 加速"开发模式。三个具体痛点:

1. **复习入口断裂**:`docs/project-story.md` 410 行,但 v0.8.3 后(B-3 监控 / v0.8.5 constrained router / v0.9 chat / c5 memory)未同步,已含错误信息;面试前需"重新刷一遍代码 + spec"才能讲清楚,~3-4h/次
2. **决策淡忘**:Harness Board 已有 ~47 个 Decision(从 spec ## § X 决策抽取),但 spec 段落是**当时写的事前权衡**,缺"事后撞坑教训"(`feedback_*.md` 的 49 篇散落 memory 没有跟 capability 绑定)
3. **模块化深度断裂**:Board 现有 62 个 capability 只有 chip(name + lit/wip/todo),点进去无内容;系统鸟瞰也不存在(只有 8 维 layer 卡片墙,层间无关系图)

### § 1.2 为什么不延伸 docs/project-story.md

| 方案 | 维护成本 | 准确性 | 复用度 |
|---|---|---|---|
| (A) 手工同步 story.md | 每次重构需手改 410 行 | 已被证明会过期(v0.8.3+) | 仅 A 场景 |
| (B) 从 git log / spec 自动生成 story | 0 维护 | 高,内容跟代码同步 | 多场景复用底座 |
| **(B') 从结构化 DeepCard 集合 render(本 spec)** | 增量填 DeepCard,按需 | 高 + 可人工修 | 5 视图全复用 |

(A) 不可持续(已撞 v0.8.3 → 现在过期);(B) 纯自动生成 prose 质量差;**(B') DeepCard 结构化 + render**:既保自动同步,又保人工质感。

### § 1.3 为什么不延伸 chat 端 (`/chat`)

/chat 是对话式问答,**反复对话讨论同一决策违背"看板"语义**。看板的本质是**决策的固化展示 + 离线复习**,不是在线对话。两个面分开:对话去 /chat,沉淀去 Harness Board Review。

---

## § 2 核心心智模型:统一底座 + 5 视图投影

```
┌─ 统一底座 (board.db sqlite + Milvus collection) ─────────────────┐
│                                                                  │
│   Capability (62 项,沿用 capabilities.yaml)                     │
│     ├─ 已有:id / name / dimension / status / derived_status     │
│     └─ 新增 DeepCard 关联(1:1)                                  │
│                                                                  │
│   DeepCard(新表 `deep_cards`)                                    │
│     • what / why / alternatives / tradeoff / lessons_learned     │
│     • metrics (optional)                                         │
│     • code_anchors / linked_decisions/specs/memories/capabilities│
│     • srs_state (confidence / last / next_review_at)             │
│     • provenance (cite back to source, 防幻觉)                   │
│     • prefill_source (llm/manual/hybrid)                         │
│                                                                  │
│   Flashcard(新表 `flashcards`,DeepCard 派生)                    │
│     • 每张 DeepCard 机械派生 2-3 张闪卡                          │
│     • SRS state 独立,每张闪卡独立 schedule                       │
│                                                                  │
│   Decision (~47 项,已有)                                         │
│   DecisionNote(用户手写,已有)                                   │
│   Memory frontmatter(跨引用,已有)                               │
│                                                                  │
│   Milvus collection `harness_board_deepcards`                    │
│     • cap_id PK / dim=1024 (qwen v3) / metadata: {dim, name, ...}│
│     • 相关推荐 cosine top-k=5                                    │
└──────────────────────────────────────────────────────────────────┘
                                │
        ┌───────────────────────┼─────────────────────────────┐
        ▼                       ▼                             ▼
   ┌────────┐         ┌──────────────────┐         ┌──────────────────┐
   │ V1 网格│         │ V2 模块深读      │         │ V3 系统鸟瞰      │
   │ (已有,│         │ (chip 翻 modal) │         │ (cytoscape 图)   │
   │ 微改) │         │ B + C 模块化     │         │ C 系统化         │
   └────────┘         └──────────────────┘         └──────────────────┘
                              ▼
   ┌────────────────┐         ┌──────────────────┐
   │ V4 故事时间线  │         │ V5 闪卡 SRS      │
   │ 难题→决策→收获 │         │ SM-2 + 模板派生  │
   │ A 面试讲项目   │         │ D 主动召回       │
   └────────────────┘         └──────────────────┘
```

**关键不变量**:
- DeepCard 是唯一内容 SoT,5 视图都是它的不同投影
- V1-V5 视图互相**跳转 = 同一 DeepCard 不同呈现**(无数据复制)
- DeepCard 内容可以**长期增量填**,不是一晚填满

---

## § 3 § 决策一:LLM 智能边界 — L2 + Milvus embedding

### § 3.1 问题陈述

复合型工具需要 LLM 介入到什么程度?在项目整体 taste("能用确定性算的不让 LLM 算" — Constrained Router / Python helper 决定论修正 / Harness Board 零 LLM)与"复习内容质量 / 维护成本"之间画线。

### § 3.2 业界 alternatives + tradeoff

| 级别 | LLM 角色 | 成本 | 幻觉风险 | 维护 |
|---|---|---|---|---|
| L0 零 LLM | 全 regex / yaml | $0 | 0 | 手填全部内容,~30h |
| L1 一次性离线 prefill | 跑一次 batch 抽 spec/memory 内容 | ~$5 一次性 | 中,需 review | ~5h prefill + ~5h review |
| **L2 (本 spec 选)** | L1 + 编辑时"AI 草拟"按钮(按需) | L1 + 按需 $0.01/次 | 中(点了你 review) | 增量按需 |
| L3 在线对话问答 | 在某张卡上 chat | 持续烧钱 | 高 | 跟 /chat 重叠 |
| L4 闪卡 LLM 评分 | 口述 → LLM 评分 | 持续烧钱 | 高 | 主流 SRS 不需 |

业界对照:
- **Anki + Mochi**(主流 SRS):L0,纯人工
- **Mem.ai / Reflect**:L3,在线对话查 note
- **Cursor + Cody(IDE 端复习)**:L2-L3,选中代码 → AI 解释
- **Anthropic Skills**(decision_framework methodology):L1,LLM-as-judge 评分后落库

我们选 L2 + Milvus(b) 平衡:**离线 batch 沉淀已有积累 + 编辑按需草拟,在线对话明确砍**。

### § 3.3 量化评估

- **LLM 成本**:一次性 prefill 估算 — 62 cap × ~3000 tokens/cap input × qwen-plus ¥0.008/1k tokens ≈ ¥1.5;按需草拟 ¥0.01/次 × 估 100 次/月 ≈ ¥1/月
- **幻觉率**:prefill 输出必须含 `provenance.quote`(≤30 字原文)+ `provenance.source`(file path + section),空 quote 字段拒绝入库 — 期望幻觉率 ≤ 5%(借鉴 c5 plan4 evidence_quote ≥ 90% 召回基准)
- **embedding 成本**:62 cap × 1 次 embedding × qwen v3 batch ≈ ¥0.05 一次性,后续 DeepCard 编辑触发 upsert ≈ ¥0.01/次

### § 3.4 决策与 escape hatch

- **决策**:L2 + Milvus embedding (b)
- **escape hatch v1.x**:`HARNESS_BOARD_LLM_LEVEL` env var 控制(`0`/`1`/`2`),L3 / L4 留 hook 不实现
- **Milvus 不可用 fallback**:相关推荐自动退到 keyword scorer(已有 `classify_layer` 扩展)+ 顶部 banner 提示

---

## § 4 § 决策二:DeepCard schema 设计

### § 4.1 字段清单(按用途分组)

```sql
CREATE TABLE deep_cards (
  cap_id           TEXT PRIMARY KEY,    -- 对应 capabilities.yaml cap.id
  -- 内容核心
  what             TEXT,                -- 做了什么 (1-2 句)
  why              TEXT,                -- 为什么这么选 (<200 字)
  alternatives     JSON,                -- [{name, brief_tradeoff}]  业界备选清单
  chosen_alternative TEXT,              -- alternatives 中我们选的那个的 name (闪卡 Q1 依赖)
  tradeoff         TEXT,                -- 我们的最终取舍 (why we picked chosen over others)
  lessons_learned  TEXT,                -- optional 撞坑教训(事后)
  metrics          JSON,                -- optional {cost, accuracy, ...}
  -- 链接图
  code_anchors     JSON,                -- [{file, line, note}]
  linked_decisions JSON,                -- [decision_id]
  linked_specs     JSON,                -- [path]
  linked_memories  JSON,                -- [path]
  linked_capabilities JSON,             -- [cap_id]
  -- SRS 学习状态
  srs_state        JSON,                -- {confidence, last_reviewed_at, next_review_at}
  -- 防幻觉
  provenance       JSON,                -- {field_name: {quote, source}, ...}
  -- 元数据
  prefill_source   TEXT,                -- 'llm' | 'manual' | 'hybrid'
  prefill_at       TEXT,                -- ISO timestamp
  last_edited_at   TEXT                 -- ISO timestamp
);
```

砍掉的字段(YAGNI):
- ❌ `version`(schema 版本号)— 硬编码 v1
- ❌ `review_count`(累计复习次数)— SM-2 不强依赖

### § 4.2 派生 vs 手补的边界

| 字段 | 派生来源 | 手补可改? |
|---|---|---|
| `what` | LLM prefill from `capability.name` + linked spec § | ✅ |
| `why` / `alternatives` / `chosen_alternative` / `tradeoff` | LLM prefill from spec/decision/memory(项目"决策四件套"格式天然好抽) | ✅ |
| `lessons_learned` | LLM prefill from `feedback_*.md` | ✅ |
| `code_anchors` | 半自动:从 `capability.derive_rule.path_glob` 提取候选,人工选定 | ✅ |
| `linked_decisions` | 自动:`classify_layer` keyword scorer(已有)+ cap_id ⊂ dimension 反查 | ✅ 手动加/去 |
| `linked_specs/memories` | **派生自 provenance**:`set(provenance[field].source for field in content_fields) | filter by file ext` 自动 dedupe 后落库 | ✅ |
| `linked_capabilities` | 自动:Milvus top-k cosine ≥ 0.7 | ✅ |
| `metrics` | 不派生,纯手补 | ✅ |
| SRS / 元字段 | 系统维护 | ❌ |

### § 4.3 量化评估

- **数据规模**:62 deep_cards × ~3kB JSON each = ~200kB sqlite,不需分表
- **检索性能**:cap_id PK lookup O(1);Milvus top-5 < 50ms(已验证 KB)
- **写入频率**:prefill 一次性,后续按需手编 < 5 次/天,sqlite 单连接足够

---

## § 5 § 决策三:5 视图形态

### § 5.1 V1 网格视图(已有,微改)

**改动**:每个 chip 增加两个视觉提示:
- 右上角小角标:**DeepCard 完成度**(`empty` 灰 / `partial` 黄 / `full` 绿)
  - 完成度 = `(what + why + alternatives + tradeoff 4 个必填字段中非空数) / 4`
  - 0 → empty;> 0 且 < 1 → partial;= 1 → full
  - `lessons_learned` / `metrics` 是 optional,不计入完成度分母
- 右下角小数字:**SRS confidence 0-5**(取 `srs_state.confidence`,无 DeepCard 时不显示)

**实现**:`_capability_chip.html` 模板加 2 个条件块,~10 行 CSS。无 LLM 介入。

### § 5.2 V2 模块深读(核心新视图)

**触发**:V1 chip 点击 → `/cap/{cap_id}` route 弹 Starlette modal(htmx swap)

**布局**:左右两栏

- **左栏(内容核心)**:what / why / alternatives / chosen_alternative / tradeoff / lessons_learned / metrics
  - 每字段下显示 provenance `quote: "..."` + `source: file#section`(可点击跳 spec)
  - 字段右上角"AI 草拟"按钮 — **点击触发 LLM 单字段生成**(prompt 限定该字段 + 该 cap 的 linked spec/memory 上下文,输出含 provenance)
  - 显示条件:字段为空 OR 字段 `prefill_source = manual`(避免 overwrite 已 review 过的 hybrid 内容)
  - 触发后字段变 `prefill_source = llm`,UI 橙色边框,等待人工 review
  - inline 编辑:click → input/textarea → blur 保存 → POST `/cap/{id}/field/{name}` → 自动改 `prefill_source = hybrid`(原为 llm)或 `manual`(原为空)
- **右栏(链接图)**:code_anchors / linked_decisions / linked_specs / linked_memories / linked_capabilities / 相关推荐 top-5
  - linked_capability 点击 → 跳 V3 鸟瞰并 highlight 该节点
  - 相关推荐 = Milvus top-5(fallback keyword)

**编辑模式**:inline,沿用 OverrideRepo / DecisionNoteRepo 模式

**Provenance UI**:`prefill_source` 着色边框
- `llm` → 橙色边框 + "AI 草拟,请 review" 角标
- `hybrid` → 蓝色边框
- `manual` → 绿色边框

### § 5.3 V3 系统鸟瞰(cytoscape 依赖图)

**触发**:V1 顶部加 "🌐 鸟瞰" 按钮 → `/overview` route

**视觉**:
- 节点 = 62 capability,颜色 = 所属 8 维(沿用 dimensions.yaml)
- 边 = `linked_capabilities` 无向集合(v1 不画因果方向);**self-loop 自动 dedupe**;两个 cap 互相 link 时 dedupe 成单边
- 布局:cytoscape `cose-bilkent`(已在 c5-plan7b 用过)
- 节点大小 = `code_anchors` 数量(信息密度)
- 节点边框颜色 = SRS confidence(灰 0 → 绿 5);无 DeepCard 的节点边框虚线
- cluster = 8 维染色 + 区域分组

**交互**:
- 点节点 → 弹 V2 modal
- 顶部工具栏:维度过滤 / 仅 lit / 仅 wip / 仅 confidence < 3(需复习)

**依赖**:cytoscape + react-cytoscapejs(已在项目)

**fallback**:cytoscape 加载失败 → 退回 8 维卡片墙(V1 放大版)

### § 5.4 V4 故事时间线

**触发**:V1 顶部 "📖 故事" → `/story` route

**时间轴**:从 git log 抓每个 cap 的首个 commit 时间(`capability.derive_rule.path_glob` 命中文件的 git log `--diff-filter=A` 输出),作为 cap 的"诞生时间"

**边界 case** — `derive_rule.type = manual` 的 cap 无 `path_glob`,无法走 git log:
- fallback 1:用 `DeepCard.prefill_at`(LLM prefill 时间)
- fallback 2:都没有 → 显示在底部"无时间归属"分组(灰色,排在最后)

**叙事弧 render**:每个 cap 渲染为"难题→决策→收获"三段式卡片
- 难题 = `why` 字段(动机部分)
- 决策 = `tradeoff` 字段
- 收获 = `lessons_learned` 字段(空则隐藏)
- 卡片底部:linked_specs + linked_decisions 链接

**工具栏**:
- 维度过滤(8 维多选)
- 时间窗筛选(slider)
- 排序:时间正序 / 倒序

**故事不再过期**:DeepCard 内容改 → 故事 render 立即跟着改

**实现**:Jinja 模板纯 render,无前端 framework

### § 5.5 V5 闪卡 SRS

**触发**:V1 顶部 "🎴 闪卡" → `/flashcards/today` route

**SRS 算法**:**SM-2**(经典 Anki 算法)
- 状态字段:`{EF: float, interval: int, repetition: int, next_review_at: ISO}`
- 自评 0-5 输入:
  - 0-2 → 重置 `repetition=0`,`interval=1`,降低 `EF`
  - 3-5 → 增 `repetition`,按 SM-2 公式更新 `interval` 和 `EF`
- 算法实现:~50 行 Python(`dashboard/derive/srs.py`)

**闪卡题目生成**(机械模板,无 LLM):每张 DeepCard 派生 2-3 张:
- **Q1**: "Capability '{name}' 在业界 alternatives 中我们选了哪个?为什么?" → A: `chosen_alternative` + 对应 alternatives 项的 brief_tradeoff
- **Q2**: "Capability '{name}' 的关键 tradeoff 是什么?" → A: `tradeoff` 字段
- **Q3**(仅 `lessons_learned` 非空时): "Capability '{name}' 撞过什么坑?" → A: `lessons_learned`

派生时机:DeepCard 编辑 → trigger `regenerate_flashcards(cap_id)`,旧 flashcard 保留 srs_state,问题/答案文本 overwrite。

闪卡 `id = f"{cap_id}::{template_kind}"`,模板 kind ∈ {alternatives, tradeoff, lessons}

**每日入口**:
- 新卡 ≤ 5 张(从 `flashcards` 表中 `srs_state.repetition = 0` 的取)
- 到期复习 ≤ 20 张(`srs_state.next_review_at <= now`)
- UI:翻面 + 0-5 自评按钮 + "跳过"按钮

**v1.x escape hatch**:`HARNESS_BOARD_SRS_ALGO=fsrs` 切换升级(留 Protocol 接口)

---

## § 6 § 决策四:数据持久化

### § 6.1 sqlite schema

沿用 `backend/data/board.db`,新增 2 表:`deep_cards`(§ 4.1)+ `flashcards`:

```sql
CREATE TABLE flashcards (
  id            TEXT PRIMARY KEY,    -- f"{cap_id}::{template_kind}"
  cap_id        TEXT NOT NULL,       -- FK deep_cards.cap_id (logical, sqlite 不强制)
  template_kind TEXT,                -- 'alternatives' | 'tradeoff' | 'lessons'
  question      TEXT,                -- 派生时缓存,DeepCard 改时重生成
  answer        TEXT,
  srs_state     JSON,                -- {EF, interval, repetition, next_review_at}
  created_at    TEXT,
  last_reviewed_at TEXT
);
CREATE INDEX idx_flashcards_cap_id ON flashcards(cap_id);
CREATE INDEX idx_flashcards_next_review ON flashcards(json_extract(srs_state, '$.next_review_at'));
```

**Schema migration**:`dashboard/state/db.py` 加 `_ensure_v2_schema()`,启动时幂等 CREATE IF NOT EXISTS(沿用 board 现有模式,不引 alembic — 跟项目 `v0.9.x-no-alembic-until-db-unify` 一致)。

### § 6.2 Milvus collection

```python
# dashboard/state/milvus_collection.py
COLLECTION_NAME = "harness_board_deepcards"
SCHEMA = {
  "cap_id": VarChar(64) PK,
  "embedding": FloatVector(1024),       # qwen text-embedding-v3
  "dimension": VarChar(32),             # metadata, for filter
  "name_cn": VarChar(128),
  "status": VarChar(16),                # lit/wip/todo
  "confidence": Int8,                   # SRS confidence 0-5
}
INDEX = {"metric": "COSINE", "type": "AUTOINDEX"}
```

**embedding source** = `f"{name_cn}\n\n{what or ''}\n\n{why or ''}\n\n{tradeoff or ''}"`(空字段时跳过该段)

**upsert 时机**:
- DeepCard `last_edited_at` 改 → upsert(异步)
- DeepCard prefill 完 → bulk insert

**相关推荐 API**:`GET /cap/{id}/related?k=5` → cosine top-5 过滤 self

### § 6.3 Milvus 不可用 fallback

- collection 不存在 / 连接超时 → 退到 `classify_layer` keyword scorer 扩展版(取 cap 的 name + linked_decisions 组合 keyword scan,top-5 by sum-of-keyword-length)
- UI 顶部 banner:"Milvus 不可用,相关推荐降级 keyword 模式"

---

## § 7 § 决策五:LLM Prefill 防幻觉机制

### § 7.1 问题陈述

LLM 一次性 prefill 是杠杆最高一步(沉淀 50+ spec / 49 memory feedback / 47 decision),但 LLM 会编造源中不存在的内容,破坏复习工具的可信度。

### § 7.2 业界 alternatives + tradeoff

| 方案 | 防幻觉强度 | 实现复杂度 | 业界例 |
|---|---|---|---|
| (a) 后处理 LLM-as-judge 评分 | 中(judge 也会幻觉) | 中 | Anthropic Skills decision_framework |
| (b) RAG cite-back(回引原文) | 高 | 中 | Perplexity / Bing Chat / Claude Citations |
| **(c) constrained JSON + provenance.quote(本 spec)** | **高** | **低** | c5 memory `evidence_quote` 校验 |
| (d) 人工 review 100% | 最高 | 极高(~5h review) | 学术 PRD 流程 |

### § 7.3 防幻觉机制设计(借鉴 c5 memory evidence_quote)

LLM prefill 调用 prompt 要求**每个内容字段必须附 quote + source**:

```python
# dashboard/scripts/prefill_deep_cards.py
PREFILL_SCHEMA = {
  "what": str,
  "_what_provenance": {"quote": str, "source": str},
  "why": str,
  "_why_provenance": {"quote": str, "source": str},
  # ... 同理 alternatives / tradeoff / lessons_learned
}
```

- 用 LLMService `response_format` constrained JSON schema(跟 v0.8.5 Constrained Router 一致)
- **provenance.quote 必须 ≤ 30 字 且 必须能在 `source` 文件内 fuzzy match 到**:
  - 校验流程:normalize 两端(strip 空白 + 删 markdown 强调字符 `*` `_` `` ` ``)→ `normalized_quote in normalized_source_text`
  - normalize 后仍未命中 → 字段 reject
  - 选 fuzzy match 而非严格 substring,避免 spec markdown 标点 / 排版差异误杀
- 校验失败的字段 **拒绝入库**(记录到 `prefill_log` 表,留人工填)
- `prefill_source` 字段标记 `llm`,UI 橙色边框,提示需 review

### § 7.4 量化评估

- **校验 substring 命中率**:期望 ≥ 90%(c5 plan4 evidence_quote benchmark)
- **未命中字段比例**:期望 ≤ 10%,留给人工补
- **prefill 全流程时长**:62 cap × ~3 secs/cap LLM(qwen-plus 流式)≈ 3 min

### § 7.5 决策

- **决策**:L2 + constrained schema + provenance.quote substring 校验
- **fallback**:LLM unavailable → 隐藏"AI 草拟"按钮 + prefill batch 跳过该 cap(留 manual)

---

## § 8 跨视图联动(全确定性,无 LLM)

| 跳转 | 来源 | 目标 | 实现 |
|---|---|---|---|
| V1 chip 点击 | `/` | `/cap/{id}` modal | htmx swap |
| V3 鸟瞰节点点击 | `/overview` | `/cap/{id}` modal | cytoscape `on('tap')` |
| V2 modal 中 linked_capability | `/cap/{id}` modal | `/overview#cap_{id}` highlight | a href + anchor |
| V4 故事卡片点击 | `/story` | `/cap/{id}` modal | a href + htmx |
| V5 闪卡"看完整内容" | `/flashcards/...` | `/cap/{id}` modal | a href + htmx |
| V2 modal 中 linked_decision | `/cap/{id}` modal | `/decisions#dec_{id}` | a href + anchor |

无前端 framework(沿用 Harness Board 已有 htmx),无 state 同步问题。

---

## § 9 测试策略

跟项目 v0.7+ 测试分层一致:

| Layer | 范围 | 数量 + |
|---|---|---|
| **L0 unit**(`dashboard/tests/unit/`) | SM-2 算法 / 闪卡模板派生 / DeepCard schema 验证 / provenance substring 校验 / keyword scorer 扩展 / git log commit-time 抽取(monkeypatched subprocess) | +30 |
| **L1 integration**(`dashboard/tests/integration/`) | sqlite roundtrip / Milvus upsert + query(real Milvus fixture,沿用 KB pattern)/ FastAPI Starlette endpoint smoke / htmx swap 渲染 | +15 |
| **L2 cassette**(`dashboard/tests/e2e/`) | LLM prefill 完整 batch 跑 6 cap × cassette replay / 整套 v1-v5 视图渲染 smoke | +5 cassette |
| **mypy strict** | `dashboard/`、`backend/scripts/prefill_deep_cards.py`(新) | — |

**dashboard 现有 65 测试不能破**。

**Playwright e2e 推迟到后续**(沿用项目"e2e deferred unless critical"模式,跟 v0.9 chat plan4b 一致)。

---

## § 10 错误处理 / 边界条件

| 情况 | 行为 | 实现 |
|---|---|---|
| DeepCard 表为空 | V2 显示"未填,点 AI 草拟 / 手填" | template fallback |
| Milvus 不可用 | 相关推荐自动 fallback keyword scorer + banner 提示 | try/except + status flag |
| LLM 单字段 prefill 失败 | 跳过,记 `prefill_log`,下次手动 retry | log + skip |
| LLM 完全 unavailable | UI 隐藏"AI 草拟"按钮 + prefill batch 跳过该 cap | env detection at startup |
| `provenance.quote` substring 校验失败 | 字段拒绝入库,记 `prefill_log.rejected_quote_field` | post-LLM validation |
| 闪卡 SRS 状态损坏(JSON parse 失败) | reset 该 flashcard.srs_state 为 default,记 warn | try/except + reset |
| `code_anchors` 中 file 已删 / line 已偏移 | UI 显示删除线 + tooltip "源文件已变更" | path.exists() + git blame line check |
| DeepCard 编辑冲突(多端) | 单用户工具,不处理 | YAGNI |
| Capability 在 yaml 中删除 | DeepCard 表保留但 UI 不显示;next prefill 清理 | soft delete |

---

## § 11 工程量估算 + 迭代节奏

按 `feedback_estimate_in_claude_code_walltime` 准则(Claude Code 加速 ~2-3x,人 bound 段不加速)。

### § 11.1 工程量分解

| 模块 | Claude Code 段 | 人 bound 段 | 累计 wall time |
|---|---|---|---|
| brainstorm → spec → 自审 → user review | — | 2h | 2h |
| writing-plans → plan 自审 → review | 1h | 1h | 3.5h |
| **底座**:DeepCard schema + sqlite migration + yaml 不变 | 1.5h | 0.5h | 5.5h |
| **底座**:`prefill_deep_cards.py` batch CLI + provenance 校验 | 2h | 0.5h | 8h |
| **底座**:Milvus collection + upsert + 相关推荐 endpoint | 1.5h | — | 9.5h |
| 内容首批样本 prefill + 人工 review 10 张 | 0.5h(自动)| 1.5h(review) | 11.5h |
| **V1 微改**:chip 角标 + confidence 数字 | 0.5h | — | 12h |
| **V2 模块深读** modal + inline 编辑 + AI 草拟按钮 | 3h | 0.5h | 15.5h |
| **V3 系统鸟瞰** cytoscape + 8 维 cluster + 钻取 | 2.5h | 0.5h | 18.5h |
| **V4 故事时间线**:git log commit-time 抽取 + 三段式 render | 2h | 0.5h | 21h |
| **V5 闪卡 SRS**:SM-2 算法 + 模板派生 + 学习入口 UI | 3h | 0.5h | 24.5h |
| 测试 + mypy + dashboard 65 测试不破 | 2h | — | 26.5h |
| 集成 smoke + 跨视图联动 wire up | 1h | — | 27.5h |

**总计 ~27.5h wall time** = ~5-6 个晚上槽位(4-5h/晚)= 1 周内可 ship。

### § 11.2 迭代节奏(建议 3 阶段)

| 阶段 | 内容 | wall time | 用户价值 |
|---|---|---|---|
| **Plan 1** | 底座(schema + prefill + Milvus) + V1 微改 + V2 模块深读 + 样本 10 张 | ~12h ≈ 2-3 晚 | B + C 模块化深读可走通 |
| **Plan 2** | V3 系统鸟瞰 + V4 故事时间线 | ~8h ≈ 2 晚 | C 系统化 + A 面试讲项目 |
| **Plan 3** | V5 闪卡 SRS + 全量样本 prefill 50+ 张 + 测试收尾 | ~7h ≈ 2 晚 | D 主动召回 |

**Plan 1 ship 时 Milvus 状态**:**collection 必须 created + DeepCard upsert path 工作**;相关推荐 endpoint 必须返回结果(实际命中 Milvus 或 fallback keyword scorer 均可,但 endpoint 不能 500)。Plan 1 不要求 Milvus 在所有环境可用,要求**降级路径完整**。

每个 Plan 独立 ship + 独立 PR + 不阻塞主路径,跟 c5 plan 1-8 节奏一致。

### § 11.3 不在范围(显式)

跟 § 0 一致:对话式问答 / LLM 闪卡评分 / LLM 出题 / FSRS / 多用户 / Mobile / 因果方向。

---

## § 12 v1.x escape hatch(留口)

| 维度 | v1 现状 | v1.x 升级口 |
|---|---|---|
| LLM 级别 | L2 | `HARNESS_BOARD_LLM_LEVEL=3` 加在线对话 / `=4` 加 LLM 评分 |
| SRS 算法 | SM-2 | `HARNESS_BOARD_SRS_ALGO=fsrs`(Protocol 接口) |
| 因果方向 | 无向 | `linked_capabilities` schema 加 `direction` 字段 |
| Embedding 模型 | qwen v3 1024d | 沿用 KB embedding choice 文档的同维互换原则 |
| 相关推荐 metric | COSINE | 加 IP / L2 选项 |

---

## § 13 实施 plan 拆分建议(给后续 writing-plans 用)

参考 § 11.2 三阶段,推荐拆 3 个 plan:

- **Plan 1 — 底座 + V2(MVP 走通)**(~12h)
  - DeepCard schema + sqlite migration + Pydantic model + L0 unit
  - `prefill_deep_cards.py` batch CLI + constrained schema + provenance 校验 + L0 unit + L2 cassette
  - Milvus collection + upsert + 相关推荐 endpoint + L1 integration
  - V1 chip 角标 + confidence 数字
  - V2 modal + inline 编辑 + "AI 草拟"按钮 + provenance UI + L1 integration
  - 样本 10 张 cap 手动 prefill + review(选最熟的: constrained router / memory bi-temporal / skills bundle / chat supervisor / 监控引擎 / ...)
- **Plan 2 — V3 + V4(系统视图 + 故事)**(~8h)
  - V3 cytoscape 图 + 8 维 cluster + 节点点击 → V2 + 工具栏 + L1 integration
  - V4 git log commit-time 抽取 + 三段式 render + 维度 / 时间窗过滤 + L0 unit
  - 跨视图联动 wire up
- **Plan 3 — V5 + 收尾**(~7h)
  - SM-2 算法 + Protocol 接口 + L0 unit
  - 闪卡模板派生 + 重生成机制 + L0 unit
  - 每日学习入口 UI(新卡 + 到期复习)+ L1 integration
  - 剩余 ~50 张 cap prefill + 人工 review
  - 测试整体收尾 + mypy strict + dashboard 65 测试不破 + L2 cassette

---

## § 14 ship checklist

- [ ] sqlite schema migration 跑通(`uv run python -m dashboard.state.db --migrate`)
- [ ] Milvus collection 创建 + index loaded + smoke search
- [ ] LLM prefill batch 跑通 ≥ 10 cap,provenance 命中率 ≥ 90%
- [ ] V1 chip 角标 + confidence 显示正常
- [ ] V2 modal 翻面 + inline 编辑 + AI 草拟按钮 + provenance UI
- [ ] V3 cytoscape 图渲染 + 8 维染色 + 点击 → V2
- [ ] V4 故事时间线 + commit-time 抽取 + 三段式 + 过滤
- [ ] V5 闪卡 SM-2 + 模板派生 + 每日入口 + 0-5 自评
- [ ] 跨视图联动 5 条全通
- [ ] dashboard 现有 65 测试不破 + 新增 +30 L0 / +15 L1 / +5 cassette PASS
- [ ] mypy strict `dashboard/` + `backend/scripts/prefill_*.py` 通过
- [ ] ruff check + ruff format clean
- [ ] `make board` + `make board-refresh` + `make board-test` 全通
- [ ] CLAUDE.md `docs/claude-context/` 加知识卡片 `harness-board-review-mode-done.md`
- [ ] README.md "当前版本" 段更新,提到 review mode + 5 视图

---

## § 15 参考资料

- SM-2 算法原始论文:Wozniak P. A. (1990) "Optimization of repetition spacing in the practice of learning"
- FSRS(留作 v1.x 升级参考):https://github.com/open-spaced-repetition/fsrs4anki
- cytoscape cose-bilkent 布局:已在 c5-plan7b MemoryGraph 用过
- htmx 模式:已在 Harness Board M1-M3 用过
- qwen text-embedding-v3:已在 KB 用过,1024d batch=10

---

## § 16 待 user review 的开放问题

1. **样本 10 张 cap 选哪些?**(Plan 1 收尾)— 我建议:`constrained_schema`(01)/ `tool_registry`(02)/ `langgraph_supervisor`(03)/ `bi_temporal_memory`(04)/ `milvus_3_collections`(05)/ `tushare_8_endpoints`(05)/ `monitoring_engine`(06)/ `escalation_protocol`(03)/ `skills_bundle`(01)/ `chat_planner`(03)— 覆盖 6 个 dimension
2. **故事时间线 V4 是否要支持手动加"叙事节点"?**(比如"v0 → v0.5 之间的总反思")— 默认不做,纯派生;后续如果发现叙事不连贯再加
3. **闪卡 V5 题目模板要不要加第 4 类**(比如 "X 模块的关键 metric 是什么?")— 默认 3 类;`metrics` 字段填充率低时加
4. **Plan 1 / 2 / 3 是否在一个 feature branch 还是分 3 个?**— 我倾向 1 个 feature branch `feat/harness-board-review-mode`,3 个 PR 顺序合并,跟 c5 单 branch 多 PR 节奏一致

---

**Spec 状态**:草稿完成,等 user review。
