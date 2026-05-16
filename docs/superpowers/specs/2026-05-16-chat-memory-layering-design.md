# Chat 模式记忆分层 — Design Spec

> **Status**: design (2026-05-16 brainstorm 产出)
> **Branch milestone**: v1.x(C.5 增量演进,不破坏现有 ship)
> **Anchor 上游**:
> - C.5 已 ship 总卡: `docs/claude-context/c5-cross-session-memory-done.md`
> - C.5 spec: `docs/superpowers/specs/2026-05-10-c5-cross-session-memory-design.md`
> - v0.9 chat C.1+C.2 spec: `docs/superpowers/specs/2026-05-09-v0.9-chat-mode-c1c2-design.md` § 1.3 决策 3
> - 参考实现: `~/.openclaw/workspace-main/hermes-agent/`(memory_provider + memory_tool)
> **工程量**: 待 plan 阶段估,预计 7-12 天(增量补完 working_blocks 接 prompt + 持仓层独立 + 便签层 session 抽取)

---

## § 0 元信息与触发(Meta)

### Why this spec

C.5 cross-session memory 已 ship,但 brainstorming 时发现两个核心问题:

1. **spec → impl gap**:`backend/app/agents/chat/prompts/memory_tool_usage.md` 模板有 `{{persona_block}}` / `{{scratchpad_block}}` 占位符,但 `chat_planner.py` 主 prompt 模板(`_PLANNER_PROMPT_TEMPLATE`)从未拼回这两块。`core_memory_append.py:73` 注释明说 "{{persona_block}} / {{scratchpad_block}} 未来回灌 system prompt 风险" — 显示这是 **设计中但未接通**。

2. **分层粒度过粗**:当前 C.5 是"working_blocks(persona + scratchpad)+ archival graph + recall"三层,但用户业务场景下"用户长期画像"(几月一变)和"当前持仓"(每周一变)的变化频率差一个数量级,合在一个 persona 块里会导致持仓改一次画像 cache 整个失效。

本 spec 重新设计为 **五层 + 混合存储 + 静态/动态 prompt assembly**,跟 Hermes(`agent/memory_provider.py` + `tools/memory_tool.py`)的工业级 agent 平台设计对齐。

### 在 v1 路线图中的位置

| Use case | 状态 | Anchor |
|---|---|---|
| C.5 跨 session memory | v1.0 ship(三层版) | `c5-cross-session-memory-done.md` |
| **Chat 记忆分层(本 spec)** | **design** | 当前 |
| B-1 / B-3+C-4 / C.1+C.2 | 已 ship | (各自 anchor) |

本 spec 是 C.5 的 **演进**,不是替换。现有 archival + 检索 + cost optimization 全部保留,只在 prompt assembly 和"画像 / 持仓 / 便签"三层上重组。

### 核心 brainstorm 决策(2026-05-16)

| # | 决策 | 选择 |
|---|---|---|
| 1 | 分层粒度 | **5 层**:画像 / 持仓 / 便签 / 档案 / 知识 |
| 2 | Prompt assembly 模式 | **静态区(画像+持仓 frozen snapshot)+ 动态区(便签滚动+召回)** |
| 3 | 静态区刷新策略 | **Open-time frozen snapshot** — 每次 session 打开(新开 / idle 回来 / 回访老 session)重读一次,单次连续会话内不变。**修正**:之前是"session 起手一次性",但 session 模型改成持久对话线程后,改成"每次 open 重读" |
| 4 | 存储模式 | **DB 底层 + markdown 视图**(混合)— 不走纯 file(Hermes 路线)也不走纯 DB(传统 SaaS) |
| 5 | 持仓层主动推送 | **接 v1.0 持仓监控引擎** — 监控触发时直接改写持仓层 PG 表,下次任一 session 打开 agent 起手看到 |
| 6 | Session 模型 | **类 ChatGPT / Claude.ai 持久对话线程** — 用户可同时开多个并发 session,可随时回访过去任一 session 继续。没有"session 结束",只有 active / cold / archived 状态 |
| 7 | 便签层存储 | **PG `chat_scratchpad` 表 + session_id 绑定持久化**(不再 TTL 销毁)。用户回到老 session 便签还在 |
| 8 | 便签抽取触发 | **三层叠加,LLM-self-managed 为主**:agent 边聊边自决调工具写(≥70%)+ c5 path_b_runner 每轮异步 fallback(≤25%)+ Celery beat 冷冻 30 天兜底(<5%)。跟 Claude Code / openclaw / Hermes 工业共识对齐 |

---

## § 1 整体架构

### 一句话定义

**五层金融业务定制 + Hermes 静态 frozen snapshot 拼装范式 + C.5 已 ship 的图档案/向量召回**,所有用户记忆走 DB 底层存储,LLM 看到的是 session 起手渲染的 markdown 视图。

### 五层定义

| # | 层名 | 装什么 | 写入触发 | 读入 prompt 时机 | 存储载体 | 字符上限 |
|---|---|---|---|---|---|---|
| **1** | **画像层** (Profile) | 用户长期稳定身份:风险偏好、投资风格、资产规模、禁忌行业、沟通习惯 | 用户明示 / 多轮信号沉淀 / onboarding 表单 | session 起手快照,session 内不变 | PG `chat_user_profile` 表 | ~1500 chars |
| **2** | **持仓层** (Portfolio) | 此刻事实:重仓股、加减仓动作、关注列表、上次买入价 | agent 工具写 / 用户同步 / **持仓监控引擎直接改写** | session 起手快照,session 内不变 | PG `chat_user_portfolio_snapshot` 表 | ~2000 chars |
| **3** | **便签层** (Scratchpad) | 本次对话线程的临时草稿:本轮候选股、刚说的临时偏好、当前讨论焦点 | session 内 agent 工具写(self-managed 主路径)+ path_b_runner 每轮异步 fallback | session 内可滚动更新,放 prompt 末尾(动态区) | **PG `chat_scratchpad` 表 + session_id 绑定持久化**(不 TTL) | ~1000 chars |
| **4** | **档案层** (Archival) | 跨 session 长期事实图:历史决策、过往观点、研究痕迹 | 每轮异步抽取 / session 结束抽取 / 便签层结束消化 | 基于本轮 query prefetch 召回 top-K,prompt 末尾 | PG + AGE + Milvus(三方一致,**复用 C.5**) | 无上限,召回 top-5 |
| **5** | **知识层** (Knowledge) | 跟用户独立的外部资料:研报、财报、政策、公告、新闻 | 离线 ingest / 监控引擎入库 | 基于本轮 query prefetch 召回 top-K,prompt 末尾 | Milvus + PG 文档 chunk(**已 ship**) | 无上限,召回 top-5 |

### Prompt 拼装结构

```
┌─ 静态区(整个 session 字节级稳定 → KV cache 命中)──────┐
│  系统角色 + 工具说明 + 行为规则                          │
│  ───────────────────────────────────────────────────  │
│  ╔══ 画像 ═══════════════════════════════════════════╗ │
│  ║  - 风险偏好: 稳健                                 ║ │
│  ║  - 不碰: ST / 高估值 / 海外中概                   ║ │
│  ║  - 资产规模: 200 万                               ║ │
│  ║  - 沟通风格: 简洁、要数据支撑、不要套话           ║ │
│  ╚═══════════════════════════════════════════════════╝ │
│  ╔══ 持仓与关注 ═════════════════════════════════════╗ │
│  ║  HOLDS:                                           ║ │
│  ║  - 茅台 600519 / 500 股 / 入仓 2026-03-15         ║ │
│  ║  - 宁德 300750 / 200 股 / 入仓 2026-04-02         ║ │
│  ║  WATCHES:                                         ║ │
│  ║  - 半导体板块、医药 ETF                            ║ │
│  ║  最近触发: [2026-05-15] 茅台净利润下滑公告        ║ │
│  ╚═══════════════════════════════════════════════════╝ │
└──────────────────────────────────────────────────────┘
┌─ 动态区(每轮变化,放末尾不影响 prefix cache)───────────┐
│  ╔══ 便签 ═══════════════════════════════════════════╗ │
│  ║  - 本轮在追的候选: 立讯精密 002475                ║ │
│  ║  - 本轮关注点: 美股 AI 链条对 A 股映射            ║ │
│  ╚═══════════════════════════════════════════════════╝ │
│  ╔══ 档案召回 top-5 ════════════════════════════════╗ │
│  ║  - [2026-03-12] 用户讨论过半导体国产替代逻辑      ║ │
│  ║  - [2026-04-20] 用户对 AI 算力链表达偏好          ║ │
│  ║  ...                                              ║ │
│  ╚═══════════════════════════════════════════════════╝ │
│  ╔══ 知识层召回 top-5 ═══════════════════════════════╗ │
│  ║  - (sim=0.82, 中信证券) 立讯精密 25Q1 业绩快报... ║ │
│  ║  ...                                              ║ │
│  ╚═══════════════════════════════════════════════════╝ │
└──────────────────────────────────────────────────────┘
user: 我想看看立讯精密能不能接 AI 算力订单
```

---

## § 2 决策 1 — 五层分层粒度

### 问题陈述

应该分几层?粒度太粗导致 cache 命中差(不同变化频率的事实混一块),粒度太细导致工程复杂度爆炸 + agent 选层困难。

### 业界 alternatives

| Paradigm | 分层数 | 主要分层 | 评价 |
|---|---|---|---|
| **MemGPT** (Letta, 2023 paper) | 3 | working / main / archive | 学术原型,通用 LLM agent 不针对业务 |
| **Hermes** (本地工具) | 2 | USER.md / MEMORY.md | 单用户本地工具,简洁但表达力弱 |
| **mem0** | 1 | 全 flat,LLM-judge conflict | extraction quality 强,但缺少长期/短期区分 |
| **Zep / Graphiti** (2025) | 1 | bi-temporal graph | 全推到图,无静态画像概念 |
| **C.5 当前 ship** | 3 | working_blocks(persona+scratchpad)/ archival graph / recall | persona+scratchpad 混在一块,变化频率不一 |
| **本 spec** | **5** | 画像 / 持仓 / 便签 / 档案 / 知识 | 金融业务定制,变化频率分级 |

### Tradeoff 分析

| 维度 | 3 层 (MemGPT/C.5) | 5 层 (本 spec) | 7+ 层 |
|---|---|---|---|
| Cache 命中率 | 中(持仓改一次,整个 persona 块失效) | 高(画像极稳定,持仓块独立) | 高 |
| 工程复杂度 | 低 | 中 | 高 |
| agent 选层困难 | 低 | 中 | 高(7 层难记) |
| 业务表达力 | 弱(画像/持仓/便签混在一块) | 强(每层语义清晰) | 过度细分,无意义 |
| 持仓监控引擎接入 | 难(写哪儿不清晰) | 直接写持仓层 | 同 5 层 |

### 量化评估方案

- **Cache 命中率**:对比 3 层 vs 5 层在 100 个真实 session 下,系统提示词前缀 unchanged 比例(目标:5 层 ≥ 85%,3 层基线 ~60%)
- **Agent 选层准确率**:50 个 golden case(用户消息 → 期望 agent 调哪个写入工具),5 层方案 ≥ 0.8
- **业务表达力**:dogfood 至少 10 个真实金融研究 session,人工审核 5 层是否能完整记录("画像层装不下的事实是不是确实该进持仓/档案")

### 为什么选 5

- **3 不够**:用户画像(几月一变)和当前持仓(每周一变)合一块,持仓改一次画像 cache 全失效;便签需要 session 边界,持仓不需要 → 性质不同
- **7 太多**:边际收益低,agent 选层困难
- **5 = 静态 2(画像/持仓)+ 动态 1(便签)+ 召回 2(档案/知识)** — 每层职责清晰,跟 Hermes 的"静态 USER.md + 静态 MEMORY.md + 动态 prefetch"哲学一致,只是多了"持仓"(金融业务特有)和"档案/知识"分开(用户私域 vs 公开知识)

---

## § 3 决策 2/3 — Prompt assembly + Frozen snapshot

### 问题陈述

静态区(画像 + 持仓)什么时候装入 prompt?有两种范式:

- **MemGPT 范式**:每轮对话开始前重新从 DB 读 → 拼进 prompt → agent 本 session 内改完下一轮看见
- **Hermes 范式**:session 起手读一次 → 拍 frozen snapshot → 整 session 不变 → agent 写入只更新 DB,下个 session 才看到

### 业界 alternatives

| Paradigm | 模式 | KV cache | 实时性 | 实现复杂度 |
|---|---|---|---|---|
| MemGPT | 每轮重读 | miss | session 内即时 | 高(每轮要 DB query + 拼装) |
| Hermes | frozen snapshot | hit | 跨 session 才生效 | 低(session 起手一次性) |
| Claude memory tool (Anthropic 2025) | 文件式 frozen snapshot | hit | 同 Hermes | 低 |
| **本 spec** | **Hermes frozen snapshot** | **hit** | 跨 session 生效 | **低** |

### Tradeoff 分析

| 维度 | MemGPT 每轮重读 | Hermes frozen snapshot |
|---|---|---|
| Prefix cache 命中 | ❌ miss(每轮静态区可能变) | ✅ hit(整 session 稳定) |
| Cost (单 session 估) | ~$0.005(基线) | ~$0.003(节省 ~40%) |
| Latency (首 token) | 高(cache miss + 重新算 KV) | 低(cache hit) |
| 实时性 | session 内 agent 改完下一轮看见 | session 内看不见,工具回执告知 |
| 工程复杂度 | 高(每轮要确保 DB query 顺序、字段顺序、空格 字节稳定) | 低(一次性渲染) |
| 适用场景 | agent 频繁自改 prompt(MemGPT 学术 demo) | 平台型 agent,实时性容忍 | 

### 量化评估方案

- **KV cache 命中率**:启用 frozen snapshot 后,prefix cache hit ratio 从 ~60% → ≥ 85%
- **Cost 实测**:50 个 session 平均成本,frozen snapshot 模式 ≤ $0.003,MemGPT 模式作 baseline ~$0.005
- **首 token latency**:p50 ≤ 500ms(cache hit),baseline 1200ms(cache miss)
- **实时性影响**:dogfood 50 session 调研用户是否在意"我改了画像本 session 看不到" — 假设零投诉(因为工具回执已告知)

### 为什么选 Frozen snapshot

- **金融场景没"必须本轮即时反映"需求**:用户不会在同一 session 里改完画像就追问;改完下个 session 看到完全可接受
- **Prefix cache 节省 40% cost** 是平台 SaaS 上量后核心成本结构
- **实现简单**:不需要每轮 query + 字节级稳定渲染
- **跟 Hermes / Claude memory tool 工业级范式对齐**:有先例,有论证

### 工具回执补救

```
agent: core_memory_append(target="profile", content="风险偏好转为激进")
tool_response: {"success": true, "note": "已更新 profile 层,本 session 内 prompt 不变,
                下个 session 起手生效", "current_state": "..."}
```

→ agent 知道写入成功且明确"下个 session 才看见",不会因为"本轮 prompt 没变化"而误判失败重试。

---

## § 4 决策 4 — DB 底层 + markdown 视图

### 问题陈述

记忆持久化用什么底层?三种路线:

- **纯 file (Hermes / Claude Code)**:单用户本地工具,markdown 文件直接当存储
- **纯 DB (传统 SaaS)**:所有记忆走 PG/MongoDB,LLM 看到的是 query 出来拼装的字符串
- **混合**:DB 底层(可查询/可扩展/合规),markdown 视图(prompt 友好/cache 友好/人类可读)

### Alternatives 对照

| 路线 | 代表 | 多用户 | 跨用户查询 | 关系图 | 向量召回 | LLM 友好 | 实现复杂度 |
|---|---|---|---|---|---|---|---|
| 纯 file | Claude Code / Hermes / Aider | ❌ 一万用户一万目录 | ❌ 不支持 | ❌ 不支持 | ❌ 不支持 | ✅ 极强 | 极低 |
| 纯 DB | 传统 SaaS | ✅ | ✅ | ⚠️ 看选型 | ⚠️ 加 vector DB | ❌ 需要拼装层 | 中 |
| **混合** | **本 spec** | ✅ | ✅ | ✅(AGE) | ✅(Milvus) | ✅(渲染层) | 中 |

### Tradeoff 分析(为什么不能纯 file)

| 维度 | 纯 file | 本 spec 混合 |
|---|---|---|
| 用户数 | 单用户 | 多用户(平台) |
| 跨用户共享知识库 | ❌ 不可能 | ✅ 知识层 Milvus 共享 |
| 关系图 / 多跳查询 | ❌ | ✅ AGE Cypher |
| 持仓监控引擎 | ❌ 不能跨用户扫 | ✅ PG `chat_user_portfolio_snapshot` 表 |
| 审计 / 合规 / PII | ❌ | ✅ DB 行级权限 |
| 单用户本地友好 | ✅ 极简 | ⚠️ 略复杂 |

### 每层落地映射

| 层 | 底层存储(程序用) | 视图层(LLM 看) | 渲染时机 |
|---|---|---|---|
| 1 画像 | PG `chat_user_profile` 表 | markdown(YAML-style header + bullets) | session 起手 |
| 2 持仓 | PG `chat_user_portfolio_snapshot` 表(监控引擎同写) | markdown(HOLDS + WATCHES + 最近触发) | session 起手 |
| 3 便签 | Redis(session-scoped TTL = 24h)或 PG session 表 | markdown(bullets) | session 内每轮动态拼装 |
| 4 档案 | PG + AGE + Milvus(C.5 已 ship 复用) | markdown(召回 top-5 单行格式) | 每轮基于 query 召回 |
| 5 知识 | Milvus + PG 文档 chunk(已 ship 复用) | markdown(召回 top-5 单行 + sim) | 每轮基于 query 召回 |

### 量化评估方案

- **多用户隔离正确性**:50 个 cross-user 投毒测试,user_A 的画像/持仓不进 user_B 的 prompt(0 失败)
- **持仓监控引擎接入 latency**:监控触发到持仓层 PG 表更新 ≤ 500ms(已知 v1.0 监控引擎 Celery 异步,符合)
- **markdown 视图渲染性能**:画像 + 持仓 5000 char 拼装 p99 ≤ 50ms

---

## § 5 决策 5 — 持仓层接监控引擎

### 问题陈述

v1.0 持仓监控引擎已 ship — Celery 异步扫描用户持仓,触发 5 类公告/事件告警。这些信号怎么进入 chat 的记忆?

### 设计

监控引擎触发时,直接 UPSERT 到 `chat_user_portfolio_snapshot` 表的 `recent_events` 字段(JSON array,最近 5 条 ring buffer):

```
持仓监控引擎(Celery 后台)
    ↓ 触发"茅台净利润下滑公告" → escalation_engine 写 escalations 表(已有)
    ↓ + 同时 UPSERT chat_user_portfolio_snapshot.recent_events(本 spec 新增)
       [
         {"ts": "2026-05-15T03:00:00", "type": "earnings_miss",
          "ts_code": "600519.SH", "summary": "茅台净利润下滑 15%"},
         ...
       ]

下个 session 起手:
    chat router → 读 chat_user_portfolio_snapshot → 渲染 markdown
    → 持仓层快照里出现"最近触发: [2026-05-15] 茅台净利润下滑公告"
    → agent 起手即知
```

### 业界对照

- Hermes / Claude memory tool:**无此机制**(单用户工具,没有"后台事件源")
- 这是本项目 **独特价值** — 把 v1.0 持仓监控引擎和 chat 记忆系统天然打通,agent 不用调工具就知道"上次离开后世界发生了什么"

### 量化评估

- monitoring → portfolio_snapshot 写入延迟 ≤ 500ms(p95)
- 1 周 dogfood:监控触发的事件出现在下个 session 持仓快照中,准确率 ≥ 0.95(漏写或多写都算失败)

---

## § 6 决策 6/7/8 — Session 模型 + 便签持久化 + 三层抽取触发

### 问题陈述

之前 spec 把 session 当成"暂态对话过程",便签 session 结束就销毁。brainstorm 撞实两个反例:

1. **用户会同时开多个独立 session**(研究医药一个 / 跟踪监控告警一个 / 尽调一个)
2. **用户会回访过去的 session 继续对话**(类 ChatGPT 设计,过去 30 天的对话点开就能继续)

这把 session 从"过程"改成了**对象**。模型修正后,便签和抽取触发必须重设计。

### 决策 6 — Session 模型:类 ChatGPT 持久对话线程

```
user (1:N)
  ├─ profile           ← 画像层,所有 session 共享
  ├─ portfolio_snapshot ← 持仓层,所有 session 共享 + 监控引擎写
  ├─ archival_graph    ← 档案层,所有 session 共享
  └─ sessions (1:N)    ← 多个并行对话线程,持久
      ├─ session_A (status: active / cold / archived)
      │   ├─ messages   (PG `chat_messages`, 已 ship)
      │   └─ scratchpad (PG `chat_scratchpad`, 本 spec 新增,session_id 绑定)
      ├─ session_B ...
```

**状态机**:
- `active` — 最近 30 天有过用户消息
- `cold` — 30 天无活动,Celery beat 触发兜底抽取后转 cold(便签 lock,history 只读)
- `archived` — 用户显式归档(便签消化 + 转只读)

### 决策 7 — 便签层持久化(PG, session_id 绑定)

之前的 Redis TTL 方案被废弃,理由:用户回访老 session 时 TTL 早已过期,便签丢失。

```sql
CREATE TABLE chat_scratchpad (
  session_id UUID PRIMARY KEY REFERENCES chat_sessions(session_id),
  user_id UUID NOT NULL,
  content TEXT NOT NULL DEFAULT '',
  token_count INT NOT NULL DEFAULT 0,
  max_tokens INT NOT NULL DEFAULT 1000,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);
```

多 tab 同 session 共享同一 scratchpad(session_id 单实例);多并发 session 各自独立。

### 决策 8 — 三层抽取触发(LLM-self-managed 为主)

**业界共识调研(2026-05-16)**:
- Claude Code(`~/.claude/CLAUDE.md` auto memory 段):agent 自己识别 4 类信号(user/feedback/project/reference)→ 调 Write tool 写 .md
- openclaw(`~/.openclaw/workspace-main/AGENTS.md` § Memory):agent 在 daily log 中自己 Write,长期 MEMORY.md 用户显式说"记下来"时更新
- Hermes(`hermes-agent/tools/memory_tool.py:513` MEMORY_SCHEMA):tool schema description 里写完整 "WHEN TO SAVE" 教程,agent 主动调用

三家都不用"批处理 session 结束"或"每轮异步增量"作主路径,**全部 LLM-self-managed**(MemGPT 哲学的实践版)。

**三层叠加方案**:

| 层 | 角色 | 触发 | 占比目标 | 复用 |
|---|---|---|---|---|
| **1. agent self-managed (主)** | LLM 在对话中自决,调 c5 6 MCP tool 之一写入 | 实时,每条用户消息后 agent 自决 | ≥ 70% 写入 | c5 MCP tools |
| **2. 每轮异步 fallback** | path_b_runner 后台扫,作 agent 漏写时的保险层 | 每轮异步,skip_gate 过滤短文本 | ≤ 25% 写入 | c5 path_b_runner + skip_gate |
| **3. 冷冻兜底** | session 30 天无活动 → Celery beat 扫便签整体抽一次 → 标记 cold | 极少触发,周一 04:00 Asia/Shanghai | < 5% 写入 | 新增 cron 任务 |

**为什么 self-managed 是主**:
- 跟 Claude Code / openclaw / Hermes 工业共识对齐
- agent 在对话语境里最清楚"这条用户表达是否值得记",信号强
- evidence_quote / reasoning 是 agent 当下生成,quality 高(c5 已 ship 的 evidence_quote substring 校验是为此设计)
- 简历叙事价值:"Letta agent-self-managed 范式" > "每轮异步 extract"

### Self-managed 三要素具体落地

| 要素 | 状态 | 文件 |
|---|---|---|
| **1. Tools(可调的 API)** | ✅ 已 ship(c5 Plan 4) | 6 MCP tools in `backend/app/mcp_server/tools/memory/` |
| **2. Behavior guide(教 agent 何时调)** | ✅ 已写,质量高 | `backend/app/agents/chat/prompts/memory_tool_usage.md` |
| **3. Agent loop(prompt 拼回主 prompt)** | ❌ **缺最后一步** | 需修改 `chat_planner._PLANNER_PROMPT_TEMPLATE` |

**Phase 1 工程量**(1-2 天):

```python
# chat_planner.py 改造
def _build_chat_prompt(self, state: ChatState) -> str:
    # 新增:渲染 self-managed 教程 + 当前 working memory 内容
    memory_guide = load_memory_tool_usage_prompt(
        persona_block=render_persona_markdown(state.user_id),
        scratchpad_block=render_scratchpad_markdown(state.session_id),
    )
    # 拼到主 prompt 开头
    prompt = memory_guide + "\n\n" + _PLANNER_PROMPT_TEMPLATE.format(...)
    return prompt
```

`memory_tool_usage.md` 内容已经包含 "Memory hygiene rules" 5 条,符合 self-managed 教学需求。本 spec 在此基础上加 3 条金融业务定制规则:

```markdown
## Domain-specific save triggers (本 spec 新增)
- 用户表达投资偏好 / 风格 / 禁忌 → core_memory_append("profile", ...) 或 写画像层
- 用户报告加减仓 / 新增关注 → archival_memory_insert(rel_type="HOLDS"|"WATCHES")
- 用户对某股表态 / 给出研究结论 → archival_memory_insert(rel_type="EXPRESSED_VIEW")
- 用户纠正之前的事实 → core_memory_replace 或 archival 重写

## Don't save
- 一次性事实查询(用户问"茅台今天涨没涨")不要记
- 闲聊 / 寒暄
- agent 自己推理出来但用户没说过的"事实"(evidence_quote substring 校验会 reject)
```

### 量化评估

| 指标 | 阈值 | 测量方法 |
|---|---|---|
| Self-managed 写入占比 | ≥ 70% | 50 个 dogfood session,看每个写入的 source(planner_initiated vs path_b vs cron) |
| Fallback 漏召率 | ≤ 0.2 | 50 case golden,agent 该写而没写的事实占比 |
| 冷冻兜底误删率 | < 5% | session 30 天后真有用户回访时,便签是否还在(应是被消化但不删,可读) |
| 抽取 quality (recall) | ≥ 0.7 | 50 case dogfood,重要事实抽出来比例 |
| 抽取 quality (precision) | ≥ 0.8 | 50 case dogfood,抽出的事实是用户真表达的比例 |

---

## § 7 跟当前 C.5 实现的 Gap 表 + 演进路径

### Gap 表

| 层 | 当前 C.5 状态 | 本 spec 状态 | Gap |
|---|---|---|---|
| 1 画像 | working_blocks.persona(已写入 PG)但**没拼回 chat planner prompt** | session 起手 frozen snapshot 进 system prompt | 需要拼回 + 字段细化 |
| 2 持仓 | 散在 archival 图(HOLDS edges),靠召回 | 独立 PG `chat_user_portfolio_snapshot` 表 + 监控引擎写 | 需要新表 + 监控引擎接 + 拎出独立块拼 prompt |
| 3 便签 | working_blocks.scratchpad(已写入)但**没拼回 prompt** | session 内动态区滚动,session 结束抽取消化 | 需要拼回动态区 + 加 session_end_extractor trigger |
| 4 档案 | ✅ 已 ship(PG + AGE + Milvus + RRF v2) | 复用 | 0 改动 |
| 5 知识 | ✅ 已 ship | 复用 | 0 改动 |
| Prompt assembly | `chat_planner._PLANNER_PROMPT_TEMPLATE` 硬编码,只塞 memory_hits + kb_hits | 静态区(画像+持仓)+ 动态区(便签+档案+知识) | 需要重组 prompt 模板 |

### 演进路径(增量,4 个 Phase)

| Phase | 范围 | 工程量 | DoD |
|---|---|---|---|
| **Phase 1** | 把 `memory_tool_usage.md` 接入 chat planner 主 prompt;working_blocks persona/scratchpad 拼回 | 1-2 天 | session 起手 prompt 头部能看到 persona + scratchpad 内容 |
| **Phase 2** | 画像层独立:新建 `chat_user_profile` 表 + 从 archival 图迁出"长期身份"类 edge + onboarding 表单 | 2-3 天 | 画像跟持仓拆开,各自独立块 |
| **Phase 3** | 持仓层独立 + 接监控引擎:新建 `chat_user_portfolio_snapshot` 表 + 监控引擎写入 hook + 起手快照渲染 | 2-3 天 | 监控触发的事件下个 session 起手即知 |
| **Phase 4** | 便签层 session 结束消化:`session_end_extractor` + 复用 LLMExtractor + path_b_runner | 2-3 天 | 50 case dogfood recall ≥ 0.7 |

### 兼容性 / 回滚

- 每个 Phase 都独立 ship,中间状态可用
- Phase 1 不破坏现有 archival 召回路径,只是 prompt 头部多两块
- Phase 2/3 涉及数据迁移,需要 SQL migration + 兼容旧 working_blocks.persona 读路径
- 出问题随时回滚到上个 Phase

---

## § 8 测试策略

### L0 unit
- 每层渲染函数:`render_profile_to_markdown` / `render_portfolio_to_markdown` / `render_scratchpad_to_markdown`(各 ≥ 5 case)
- session 起手快照拼装:静态区字节级稳定测试(同一 session 多轮,前缀不变)
- session_end_extractor:便签 → archival 抽取 ≥ 10 case

### L1 integration
- 完整 chat 一轮:静态区(画像 + 持仓) + 动态区(便签 + 召回)全部出现在最终 prompt
- 监控引擎触发 → 持仓层 PG 更新 → 下个 session 起手快照含该事件(端到端)
- 跨用户隔离:user_A 的画像不进 user_B 的 prompt

### L2 cassette / dogfood
- 50 session real-LLM eval:KV cache hit rate ≥ 85%
- 50 case golden:agent 选层准确率 ≥ 0.8
- cost 实测:平均 ≤ $0.003 / session

### L3 dogfood
- 10 个真实金融研究 session 至少 1 周,人工审 5 层是否能完整记录用户事实

---

## § 9 brainstorm review 锁定记录(2026-05-16)

### 已锁(review 通过)

| # | 决策点 | 锁定结果 |
|---|---|---|
| 6 | session 边界 | **类 ChatGPT 持久对话线程**;active / cold / archived 状态机;多 tab 同一 session 共享便签;多并发 session 各自独立;不存在"session 结束"概念,只有 30 天无活动转 cold |
| 7 | 便签层存储 | **PG `chat_scratchpad` 表 + session_id 绑定持久化**,不用 Redis,不 TTL |
| 8 | 便签抽取触发 | **三层叠加**:agent self-managed 主路径(≥70%)+ path_b_runner 每轮异步 fallback(≤25%)+ Celery beat 30 天冷冻兜底(<5%) |
| - | 回滚策略 | **D 共存,不迁旧数据**:旧档案图 HOLDS edges 原封不动,新画像/持仓 PG 表只装上线后新数据;Phase 2/3 失败可一键关掉新表读路径 fallback 回旧路径 |
| - | Self-managed 三要素 | Tools + Behavior guide ✅ 已 ship;**Phase 1 缺第三步:把 `memory_tool_usage.md` 拼回 chat_planner 主 prompt + 加 3 条金融业务定制 save triggers** |

### 留 plan 阶段 decide 的细节(细到 plan 才能合理决策)

1. **画像层 schema 字段**:`risk_appetite` / `style` / `assets_scale` / `forbidden_industries` / `communication_style` — 结构化字段还是自由文本?(plan 阶段看 schema design 决定)
2. **持仓层 schema 跟 v1.0 `portfolio` 表对齐**:直接 view(只读)还是 sync 表(双写)?需要看 v1.0 monitoring_engine 写哪个表
3. **各层字符上限具体数值**:画像 1500 / 持仓 2000 / 便签 1000 是直觉值;plan 阶段加 dogfood 校准 loop
4. **画像层信号沉淀规则**:"多轮稳定" 是 LLM judge 还是规则?需要 plan 阶段设计 `profile_signal_consolidator`
5. **3 条 domain-specific save triggers 的精确 prompt 表述**:plan 阶段配合 dogfood 调优

---

## § 10 简历叙事(可直接抄)

> "在 C.5 cross-session memory ship 后,发现 spec → impl gap:working_blocks 模板存在但从未拼回 chat planner prompt,且 working_blocks 把'长期画像'和'当前持仓'(变化频率差一个数量级)混在一个 persona 块,导致 KV cache 命中率低。
>
> 重新设计为**五层 + 静态/动态 prompt assembly + DB 底层 markdown 视图**:画像层(几月一变,frozen)+ 持仓层(每周一变,frozen + 接监控引擎主动推送)+ 便签层(session 内动态)+ 档案层(召回) + 知识层(召回)。
>
> 设计参考 Hermes 工业级 agent 平台的 `agent/memory_provider.py` 跟 `tools/memory_tool.py`,用 frozen snapshot 模式保 prefix cache;在 Hermes 的两文件(USER.md / MEMORY.md)基础上做金融业务细化,加'持仓层'作为业务特色(接 v1.0 持仓监控引擎,实现 agent 离开后世界发生的事 session 起手即知)。
>
> 拒绝纯 file(Hermes 路线) — 平台是多用户的,跨用户共享 KB + 关系图 + 向量召回必须 DB;拒绝纯 DB(传统 SaaS 路线) — LLM 看到的应该是 markdown 视图,prompt 友好 + cache 友好 + 人类可读 git diff 友好。最终选**DB 底层 + markdown 视图**混合架构。
>
> 量化目标:KV cache hit ≥ 85% / 单 session cost ≤ $0.003(基线 $0.005)/ agent 选层准确率 ≥ 0.8 / 监控引擎触发到持仓层 ≤ 500ms / session 结束抽取 recall ≥ 0.7。"

---

## § 11 关键文件 ref

### 设计参考
- Hermes: `~/.openclaw/workspace-main/hermes-agent/agent/memory_provider.py`(MemoryProvider ABC)
- Hermes: `~/.openclaw/workspace-main/hermes-agent/tools/memory_tool.py`(MEMORY.md / USER.md 文件后端)

### 当前实现(Gap 起点)
- `backend/app/agents/chat/prompts/memory_tool_usage.md`(模板 — 含 `{{persona_block}}` / `{{scratchpad_block}}` 占位符)
- `backend/app/agents/chat_planner.py:226-265`(`_PLANNER_PROMPT_TEMPLATE` — **缺少 persona/scratchpad 拼回**)
- `backend/app/agents/chat_planner.py:392-424`(`_build_chat_prompt` — 当前只拼 memory_hits + kb_hits)
- `backend/app/memory/persona_populator.py`(session 起手 hook — 已写 PG,缺拼回)
- `backend/app/memory/working_blocks.py`(append/replace 纯函数层)
- `backend/app/mcp_server/tools/memory/core_memory_{append,replace}.py`(MCP tool — 已写入,但 prompt 看不到)

### 复用(已 ship)
- `backend/app/memory/retriever.py`(3-way hybrid)
- `backend/app/memory/rrf.py`(time-aware RRF v2)
- `backend/app/memory/extractor.py`(LLMExtractor)
- `backend/app/memory/path_b_runner.py`(Path B Celery async)
- `backend/app/orchestration/memory_kb_router_node.py`(memory_hits + kb_hits 召回)
- `backend/app/services/monitoring_engine.py`(v1.0 持仓监控)

### 新增(待 Plan)
- `backend/app/memory/profile_layer.py`(画像层渲染 + CRUD)
- `backend/app/memory/portfolio_layer.py`(持仓层渲染 + CRUD + 监控引擎 hook)
- `backend/app/memory/scratchpad_layer.py`(便签层渲染 + session-scoped CRUD)
- `backend/app/memory/session_end_extractor.py`(便签 → 档案抽取 trigger)
- `backend/scripts/migrations/2026-05-1X-memory-layering.sql`(`chat_user_profile` + `chat_user_portfolio_snapshot`)
