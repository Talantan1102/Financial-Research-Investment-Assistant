# Harness Board Design Spec

**作者**:Talantan1102
**起草**:2026-05-07
**状态**:Spec 已对齐 → 进 writing-plans
**类型**:开发者元工具(meta-tool)spec,自用,不进产品

---

## § 0 元信息与范围

本 spec 设计 **Harness Board** —— 一个独立轻量 web 工具,以 **8 维 LLM Harness Capability Matrix + Kanban Toggle** 视角追踪 financial-research-assistant 项目的 capability 状态,辅以决策档案,服务作者高频自用("每天多次")的"早上启动看全貌 + 挑今天做什么"工作流。

**重启 brainstorming 起因**:2026-05-06 起草过同主题 spec(commit `59ed65b`),设计了双形态(admin + public portfolio)+ Status hero 数字 + Roadmap matrix + Timeline 等 6 个视图,工程量 9-13 天。作者 2026-05-07 决定推翻重做,重新 brainstorming 后聚焦收紧到:**仅 D + B 两视图 / 仅自用无 portfolio / 独立轻量 web 形态 / 工程量 3-5 天**。

被删 spec 的方法论(8 维视角论证 / Capability Matrix vs progress bar 论证 / 业界对齐表)有可复用价值,本 spec § 5 / § 11 节段保留这些骨架,但功能集严格依本次 brainstorming 的决策。

**前置 spec 引用**:
- `2026-05-05-v0.9+-roadmap-and-long-running-task-scheduling.md`(本工具属于 § 6 brainstorm 队列)
- `2026-05-05-v0.8.5-constrained-router-design.md`(Skills bundle 是 capability "01.Skills bundle" 来源)
- `2026-05-04-v0.8.4-b1-single-deep-design.md`(7-stage Critic 是 capability "03.7-stage Critic" 来源)
- `2026-05-02-v0.7-kb-search-milvus-design.md`(Milvus + 13 corpus 是 capability "05.Milvus 3 collection" 来源)

**关键 memory 引用**:
- `user_portfolio_target` — 求职定位 LLM 应用算法 + infra
- `feedback_design_doc_format` — 四件套(问题陈述 + 业界 alternatives + tradeoff + 量化评估)
- `feedback_no_portfolio_simplification` — 不能用个人项目借口降严谨度;但允许针对实际诉求精简
- `feedback_estimate_in_claude_code_walltime` — 工期按 Claude Code wall time
- `feedback_python_m_path_dual_context` — `python -m` 在 project root 跑必须显式 sys.path 策略
- `project_eval_pipeline_contract` — golden 测试范式的延续
- `project_v1_route_product_first` — Product-first;不预先抽象未撞痛点(本 spec 砍掉跨维度依赖追踪等未撞痛点的特性)
- `feedback_third_party_plugin_defaults` — 引用 plugin 默认前 spike(htmx / starlette templates 实施时实测)

**不在范围**(显式排除,§ 10 详述):
- 公开页 / portfolio 模式(仅自用)
- Status Dashboard 数字 hero(选今日聚焦 hero)
- Roadmap Timeline / 矩阵视图 / Narrative Wiki
- Cost / test pass / commit / blocker 边角数字
- 跨维度依赖追踪(算法→后端→前端 drift)
- Mobile 端 / E2E browser test / Visual regression
- npm / 前端框架(htmx vendored + CSS 手写)
- GitHub Actions / CI 直连 / 自动 LLM 周报

---

## § 1 痛点动机:为什么现在做

### § 1.1 工作流痛点

作者从 v0~v0.8.5 期间是"晚上在场全程值守",markdown spec + memory 索引够用。v0.9+ 起进入"白天通勤异步 + 9 模块并行"工作流,markdown 索引方式开始失效,具体痛点:

| 痛点 | 描述 |
|---|---|
| **A 早上启动失焦** | 9 个模块并行,昨天做到哪、今天挑啥要翻 git log + memory + spec 才能拼出 |
| **B 优先级模糊** | "Memory 1/6 lit 是弱项 → 该重点开发"这种判断没有视图直接呈现 |
| **C 全局体量看不见** | 想一眼看到"整个项目的 LLM harness 工程长什么样"没有入口 |
| **D 决策追溯成本** | "为什么砍 D2"、"百炼切换原因"散落在 memory + spec + commit message,翻起来累 |

A + B 高频(日常)/ C 中频(周度)/ D 低频(月度)。本 spec 满足 A + B + C 进主视图(D + B Toggle + Hero),D 进独立 route(`/decisions`),不打扰主视图。

### § 1.2 诉求边界(从 brainstorming 收敛)

| 维度 | 决策 | 来源 |
|---|---|---|
| 形态 | D + B Toggle 混合 | brainstorming Q1 |
| 用法 | 高频(每天多次)+ 仅自用 | brainstorming Q2 |
| 工程形态 | 独立轻量 web | brainstorming Q3 |
| 切片 | 8 维 LLM Harness + App Shell 第 9 行 | brainstorming Q4 |
| 维护 | 半自动(派生 lit/todo + 手填 wip) | brainstorming Q5 |
| Hero | 今日聚焦(日期 + wip 一行) | brainstorming Q6a |
| 决策日志 | 独立 route `/decisions` | brainstorming Q6b |
| Layout | Toggle 切换(非 split 同屏) | brainstorming Q7 |

---

## § 2 决策一:形态选型 — 独立轻量 web

**问题陈述**:dashboard 工程形态怎么选?嵌入现有 frontend / 独立轻量 web / CLI / Markdown 静态站 / IDE 扩展。

**业界 alternatives**:

| 形态 | 描述 | 业界示例 |
|---|---|---|
| 嵌入现有 frontend | React 路由 + backend `/api/dashboard/*` | Stripe Dashboard / Linear |
| **独立轻量 web(选用)** | Starlette + htmx + Jinja2 + sqlite | htmx.org demo / Phoenix LiveView 风格 |
| CLI tool | 终端命令直出 | tig / lazygit / k9s |
| Markdown 自动生成 + 静态 HTML | parser 输出 .md / .html | github-readme-stats / mkdocs |
| IDE 扩展(VSCode) | 平台绑定 | GitLens / VSCode Test Explorer |

**Tradeoff**:

| 形态 | 优 | 劣 |
|---|---|---|
| 嵌入 frontend | 复用 React 栈 + 主要 ROI 是 portfolio 公开页 | 公开页砍掉后只剩负担:产品 tests / auth / router 共享 → 改 dashboard 撞产品 |
| **独立轻量 web** | 零产品耦合 + D/B 视图在 web 表达力强 + htmx form post 适配 wip 切换 | 多一个进程要管(`make board` 启停) |
| CLI | 启动快 + 与 git/poe 工作流融合 | D 视图 8 维 × N capability 在 ascii 表横向无法并列阅读 |
| Markdown 静态 | 极简,无 build | 不能手填 wip(B Kanban doing 列空) |
| IDE 扩展 | 启动成本最低(已开 IDE) | 工程量大 + 平台绑定 + 无可移植性 |

**量化评估**:

- **工程量**:嵌入 frontend 6-9 天 / 独立 web 3-5 天 / CLI 2-3 天 / Markdown 2 天(功能降级)/ VSCode 8-10 天
- **启动成本**(用户高频体验):嵌入(已开浏览器+新 tab)和独立(`make board`+新 tab)~等价;CLI 最快;IDE 最快(已开)
- **D + B 表达力**:web/IDE 强 / Markdown 中(无手填)/ CLI 弱(横向受限)
- **产品耦合负担**:嵌入 100% / 独立 0% / 其他 0%

**选用独立轻量 web**(brainstorming Q3 选 #2):
- 公开页砍掉后嵌入主要 ROI 消失,只剩耦合负担
- 工程量 3-5 天 / 零耦合 / D + B 表达力强,综合最优
- 即使后续想加 portfolio,加独立 route 即可,不必返工

---

## § 3 决策二:Capability Matrix 数据模型 + 三态

**问题陈述**:每条 harness 泳道用什么"完成度指标"?进度百分比 / Capability Matrix / Maturity Level / 加权 score?

**业界 alternatives**:

| 指标 | 描述 | 业界示例 |
|---|---|---|
| Progress percentage | 已完成 / 总数 % | 通用 PM 软件 |
| **Capability Matrix(选用)** | 每层若干离散 capability,状态 = lit / wip / todo | OWASP Maturity Model / Anthropic Skills 计数 / 游戏技能树 |
| Maturity Level | Level 0-5,每级有 checklist | MLOps maturity / CMMI |
| Capability score | 每 capability 加权 + 0-10 评分 | 内部能力评估 |

**Tradeoff**:

| 指标 | 优 | 劣 |
|---|---|---|
| Progress % | 直观一目了然 | "LLM harness 永远可以更深"——百分比无意义,每个维度永远 < 100% / 弱项被平均掉看不见 |
| **Capability Matrix** | 无虚假"完成度"暗示 + 具体能力点显眼 + 简历可拷贝点亮项 | 需要维护 capability 清单(yaml,半手动) |
| Maturity Level | 业界已知模型 | 离散等级粒度太粗(L1/L2 之间巨大跳跃) |
| Capability score | 量化精细 | 评分主观 + 权重难定 |

**量化评估**:

- **信息密度**:Capability Matrix 每屏显示 ~ 60 具体 capability;Progress % 每屏 ~ 8 个数字
- **简历拷贝度**:Capability Matrix 直接拷贝"已点亮 LangGraph + Send + subgraph + 7-stage Critic"作为 bullet;Progress % 无法拷贝
- **维护成本**:Capability Matrix 需 yaml 配置(每 layer 6-9 项,~ 60 项,业界 best practice 出新 capability 时手动追加,年度级别频率);Progress % 由 task 数自动算
- **弱项识别**:Capability Matrix 04 Memory(1/6)是显眼弱项;Progress % 下 Memory 被淹没

**选用 Capability Matrix**(brainstorming Q1 用户原话:"进度条感觉很鸡肋,因为每个维度永远都有可以优化的地方")。

### § 3.1 三态语义

| 状态 | 颜色 | 派生规则 | 手填覆盖 |
|---|---|---|---|
| **lit 已点亮** | 绿 #14532d / #86efac | derive_rule 命中 | 允许 force-lit override |
| **wip 进行中** | 橙 #7c2d12 / #fdba74 | 完全手填(代码无信号) | 全手填 |
| **todo 待做** | 灰 #1e293b dashed border / #64748b | derive_rule 默认 | 允许 force-todo override(撤回 force-lit) |

**视觉规范不变量**:`todo` 视觉权重必须最低(虚线灰),不能让"未做"看起来比"已做"更突出,否则挫败感强。

### § 3.2 Capability 总数 anchor

初版 62 项(8 layer × 6-9 项 = 8+8+9+6+8+7+9+7,App Shell 第 9 行另算 6 项 mini stat,不进 capability 计数),lit 35 / wip 0 / todo 27 是 v0.9.x 时 anchor:

| Layer | Lit count | Total | 已点亮(lit)样例 |
|---|---|---|---|
| 01 Prompt & Context | 4 | 8 | multi-tier signature / constrained schema / Skills bundle (17) / per-task registry |
| 02 Tools & Function Calling | 5 | 8 | Tool Registry / Schema-validated I/O / DI mock-real / 5 reliability layer / 8 financial tools |
| 03 Orchestration / Multi-Agent | 6 | 9 | LangGraph / 5 agents / Send + subgraph / 7-stage Critic / SSE / SqliteSaver |
| 04 Memory ⚠ | 1 | 6 | session(SqliteSaver) |
| 05 RAG / Knowledge | 5 | 8 | Milvus 3 collection / embedding + cache / 13 corpus / Bocha web / reliability layer |
| 06 Guardrails & Auto-Repair | 4 | 7 | Constrained Router / Pydantic schema / LangGraph retry / per-step Critic |
| 07 Eval & Observability | 6 | 9 | EvalRunner / TraceService / LLM-as-Judge / 12 golden / Cassette L2 / 289 tests |
| 08 Cost & Routing | 4 | 7 | Tier Router / Pricing / Cost budget / max_tokens calibration |
| **Total** | **35** | **62** | |

App Shell 第 9 行 6 项(Frontend / Backend / Auth / Database / Connectors / Infra)各显示**派生百分比** mini stat(具体公式 § 12.3 implementation 决定),**不进 capability 计数**。

---

## § 4 决策三:半自动维护(派生 lit/todo + 手填 wip)

**问题陈述**:capability 状态怎么变?

**业界 alternatives**:

| 候选 | 描述 |
|---|---|
| A 全代码 grep 派生 | parser 扫源码推断状态 |
| B 全手填 yaml | yaml 列所有 capability + 状态 |
| **C 半自动(选用)** | grep 派生 lit/todo + wip 完全手填 |
| D 代码 inline marker | 代码注释里 `# CAPABILITY: 04.long_term · WIP` |

**Tradeoff**:

| 候选 | 优 | 劣 |
|---|---|---|
| A 全派生 | 自动一刷新就新 | wip 语义缺失,只能 lit/todo 二态;B Kanban doing 列永远空 |
| B 全手填 | 简单可控 | 双写负担(代码改了 yaml 没改 → drift);"声明 lit 但代码删了"=简历翻车 |
| **C 半自动** | 平衡:lit/todo 自动反映代码,wip 有真实手填语义 | derive_rule 写一次(yaml grep pattern) |
| D inline marker | 跟代码贴近,git diff 看变化 | 污染产品代码;不同语言注释格式(`#`/`//`/`"""`)grep 难精准 match |

**量化评估**:
- **代码 drift 抗性**:A/C/D 强(派生命中即时反映);B 弱(需手改 yaml)
- **wip 语义保真**:C/D 强(手填 / inline marker);A 缺失;B 看勤奋度
- **维护负担**:A 最低(无 yaml)/ C 中(yaml + dashboard toggle wip)/ B 高(双写)/ D 中(commit 时同步注释)
- **代码侵入度**:D 唯一非零(每 capability 在源码留 marker)

**选用 C 半自动**(brainstorming Q5):
- wip = "我正在做这个" 是 Kanban doing 列的命脉,代码层面跑不出"在做"信号
- 维护负担:每 capability 写一行 yaml grep pattern(写一次)+ dashboard 编辑模式 toggle wip(交互级)
- 派生 lit/todo 防代码 drift(改完代码 dashboard 自动反映)

### § 4.1 derive_rule 类型

5 类(实施时按需扩):

| type | 用途 | 示例 |
|---|---|---|
| `code_grep` | 源码正则匹配 | `pattern: 'def chat\(.*tier:'`,`path_glob: 'backend/app/services/llm_*.py'` |
| `file_exists` | 某路径文件存在 | `path: 'backend/app/services/skills/registry.py'` |
| `spec_section` | 某 spec 中有命名 § | `path: 'docs/superpowers/specs/2026-05-05-v0.8.5-*.md'`,`section_pattern: '## §.*Constrained Router'` |
| `memory_frontmatter` | memory frontmatter 含 `version: vX.Y` | `path: 'memory/project_v0.8.5_*.md'` |
| `manual` | 完全手填(用于 wip-only capability,如"长期记忆"还没开工) | — |

### § 4.2 手填覆盖规则

- 派生层每次刷新重算 capability 状态
- 状态 = `derived_state` UNLESS `manual_override` 存在
- `manual_override` 存表 `capability_override(capability_id, status, reason, set_at)`
- override 永久有效直到作者主动清除(派生层不擦除手填)
- 用户可在编辑模式 force-lit / force-todo / set-wip(三种 override)

---

## § 5 视角:8 维 LLM Harness + App Shell 第 9 行

### § 5.1 决策:用 LLM Harness 视角切片

**问题陈述**:维度怎么切?直觉是按代码归属切(前端/后端/数据库/算法/运维),但这种视角在 LLM 应用项目中**把简历亮点(prompt/agent/memory/RAG/eval)藏在"算法"一格里看不见**,Memory 弱项被 backend 70% 平均掉。

**业界 alternatives**:

| 切法 | 来源 |
|---|---|
| **LLM Harness 8 维(选用)** | a16z AI Stack / Sequoia GenAI Stack / LangChain conceptual layers / MCP 协议 |
| 应用工程 5-7 维(FE/BE/DB/Algo/DevOps) | 通用软件项目 |
| 研发职能切法(PM/Design/QA/SRE) | 大型公司 |
| DDD 用户价值流(按业务域) | 大型 SaaS 多业务线 |
| FURPS 质量属性 | SLA 重产品 |

**Tradeoff**:

| 视角 | 优 | 劣 |
|---|---|---|
| **LLM Harness 8 维** | 简历叙事 1:1 对齐 LLM 工程师 JD;每条泳道天然有"已有 + 待做" | 应用层"前端/Auth"无主泳道(下沉到 App Shell catch-all) |
| 应用工程 5-7 维 | 直觉对齐文件结构 | LLM 亮点被压缩;Memory 缺口被平均掉 |

**量化评估**:
- **简历对齐度**:8 维和 LLM 工程师典型 JD 关键词重合度 ~ 85%,5 维重合度 ~ 30%
- **弱项暴露度**:8 维下 Memory(1/6)是显眼弱项;5 维下 Memory 被 Backend(70%)淹没
- **学习成本**:8 维对作者零成本(memory 中已熟悉 LangGraph/Send/subgraph/critic 等术语)

**选用 8 维 LLM Harness**(brainstorming Q4 接受)。

### § 5.2 8 个 Harness 维度

| # | 中文名 | English | 业界对应(详 § 11) |
|---|---|---|---|
| **01** | 提示与上下文 | Prompt & Context | Anthropic Skills / OpenAI Cookbook |
| **02** | 工具与函数调用 | Tools & Function Calling | MCP / OpenAI Functions / Anthropic Tools |
| **03** | 编排与多智能体 | Orchestration / Multi-Agent | LangGraph / CrewAI / Anthropic Subagents |
| **04** | 记忆层 | Memory | Letta / mem0 / LangChain Memory |
| **05** | 检索增强 | RAG / Knowledge | LlamaIndex / Pinecone / Weaviate |
| **06** | 护栏与自修复 | Guardrails & Auto-Repair | NeMo Guardrails / Pydantic AI / Constitutional AI |
| **07** | 评测与可观测 | Eval & Observability | LangSmith / Helicone / Arize / Phoenix |
| **08** | 成本与路由 | Cost & Routing | Portkey / NotDiamond / Martian |

### § 5.3 App Shell 第 9 行 catch-all

8 维之外的应用层工程完整性,**不另开主泳道,压缩为底部一行 mini stat**:虚线边框、灰调、单行百分比。

App Shell 6 项:Frontend / Backend / Auth / Database / Connectors(tushare/bocha/milvus 客户端层,但 corpus/retrieval 算 RAG)/ Infra/CI

**为什么不进主泳道**:
1. 这些是工程基线(任何 web 应用都需要),不是 LLM harness 差异化亮点
2. 在主泳道中会稀释 harness 维度的视觉权重
3. 仍需保留(单纯不显示会看不见"工程完整性"维度)

App Shell 6 项各显示派生百分比(简单 file count / loc / 已知 capability hit ratio,实施时按 derive_rule 决定具体公式),**不进 60 项 capability 计数**。

---

## § 6 5 层架构

### § 6.1 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│ ① Source · 只读现有资产 (无侵入)                              │
│   backend/app/** · docs/superpowers/** · memory/*.md        │
│   git history · frontend/**(仅 App Shell 行用)              │
└────────────────┬────────────────────────────────────────────┘
                 │ derive (纯函数 parser,可缓存)
                 ▼
┌─────────────────────────────────────────────────────────────┐
│ ② Derive Layer                                              │
│   capability_resolver · decision_extractor · path_router    │
└────────────────┬────────────────────────────────────────────┘
                 │ persist (全量替换 + 手填合并)
                 ▼
┌─────────────────────────────────────────────────────────────┐
│ ③ State · sqlite at backend/data/board.db                   │
│   capability_override · decision_tags · derived_snapshot    │
└────────────────┬────────────────────────────────────────────┘
                 │ Starlette routes
                 ▼
┌─────────────────────────────────────────────────────────────┐
│ ④ Server · Starlette + Jinja2 + htmx (~ 200 LoC)            │
│   GET / · GET /decisions · POST /wip-toggle · POST /refresh │
└────────────────┬────────────────────────────────────────────┘
                 │ htmx form post + Jinja partial render
                 ▼
┌─────────────────────────────────────────────────────────────┐
│ ⑤ UI · 浏览器 (本地 only)                                    │
│   Hero (今日聚焦) + D/B Toggle + /decisions                  │
└─────────────────────────────────────────────────────────────┘
```

### § 6.2 关键不变量

1. **Source 层只读**——派生层绝不写 backend/app/ 或任何产品代码
2. **Derive 层是纯函数**——同 source 输入必产出同输出(测试 golden 模式的基础,§ 9.1)
3. **手填覆盖永久**——除非用户主动清除,派生层不擦手填
4. **本地 only**——server 绑 `127.0.0.1:8910`,无鉴权,无外部访问

### § 6.3 Source Layer 数据来源 + 维度路由

`config/dimensions.yaml`(8 维 path/keyword routing,初版 anchor):

| 维度 | 主路径 | 关键词(辅助) |
|---|---|---|
| 01 Prompt & Context | `backend/app/services/llm_*` `backend/app/services/skills/*` | "tier", "schema", "Skills" |
| 02 Tools & Function Calling | `backend/app/tools/**` `backend/app/services/tool_registry*` | "Protocol", "tool" |
| 03 Orchestration / Multi-Agent | `backend/app/agents/**` `backend/app/orchestration/**` | "LangGraph", "agent", "subgraph" |
| 04 Memory | `backend/app/services/memory_*` `backend/app/services/checkpointer*` | "Memory", "Saver", "checkpoint" |
| 05 RAG / Knowledge | `backend/app/services/{milvus,bocha,kb,corpus,embedding}_*` | "embedding", "retrieve" |
| 06 Guardrails & Auto-Repair | `backend/app/services/{constrained_router,critic,validator}_*` | "Schema", "Pydantic", "retry" |
| 07 Eval & Observability | `backend/app/services/{eval,trace,judge,recorder,monitoring}*` `backend/tests/**` | "EvalRunner", "TraceService", "Judge", "golden" |
| 08 Cost & Routing | `backend/app/services/{tier_router,pricing,cost_budget,quota,rate_limiter}*` | "TierRouter", "pricing" |

**冲突解决**:文件命中多个 pattern 时,**更具体的优先**。规则配置在 `dimensions.yaml`,人可读人可改。

### § 6.4 Derive Layer 4 个模块

```python
# dashboard/derive/path_router.py
def classify_path(path: str, dimensions_config: DimensionsConfig) -> DimensionId:
    """路径 → 8 维 + App Shell + 'unknown'"""

# dashboard/derive/capability_resolver.py
def resolve_capability_status(
    capability: CapabilityConfig,
    code_index: CodeIndex,
    spec_index: SpecIndex,
    memory_index: MemoryIndex,
) -> CapabilityStatus:
    """按 derive_rule 类型分发,返回 lit/wip/todo"""

# dashboard/derive/decision_extractor.py
def extract_decisions(memory_dir: Path, specs_dir: Path) -> list[Decision]:
    """memory frontmatter + spec § 决议节段 → Decision 列表"""

# dashboard/derive/snapshot_builder.py
def build_snapshot(...) -> Snapshot:
    """聚合上述 → 单个 Snapshot (sqlite payload)"""
```

**关键不变量**:Derive 层是纯函数 → § 9.1 golden 测试基础。

### § 6.5 State Layer · sqlite 3 张表

```sql
-- backend/data/board.db schema

CREATE TABLE derived_snapshot (
  id INTEGER PRIMARY KEY,
  refreshed_at TIMESTAMP NOT NULL,
  payload JSON NOT NULL  -- 全量派生快照,每次刷新替换
);
-- 仅保留最新一行,无历史保留

CREATE TABLE capability_override (
  capability_id TEXT PRIMARY KEY,  -- e.g. "01.multi_tier_signature"
  status TEXT NOT NULL,            -- 'lit' | 'wip' | 'todo'
  reason TEXT,
  set_at TIMESTAMP NOT NULL
);

CREATE TABLE decision_tags (
  decision_id TEXT PRIMARY KEY,    -- 由 decision_extractor 输出的稳定 hash
  user_note TEXT,
  set_at TIMESTAMP NOT NULL
);
```

**为什么 sqlite 不复用现有产品 DB**(`eval.sqlite` / `monitoring.sqlite`):
- 隔离:dashboard meta 数据不进产品 schema
- 迁移独立:dashboard 改不触发产品 migration
- 备份独立:`board.db` 可单独 git ignore + 重建(数据可派生)

**为什么 sqlite 不用 JSON 文件**:
- 项目栈已有 sqlite(SqliteSaver / TraceService),复用
- 多读少写场景 sqlite 更稳

### § 6.6 Server Layer · Starlette + htmx

```
GET  /                    → 主视图 (Hero + Tab + D/B 视图)
GET  /decisions           → 决策列表 + filter
POST /wip-toggle          → 设置 capability override status
POST /refresh             → 强制 rerun derive(默认 lazy)
GET  /partials/d-view     → htmx partial(切 tab 时)
GET  /partials/b-view     → htmx partial
GET  /partials/decisions  → htmx partial(filter 触发)
```

**鉴权**:无,绑 `127.0.0.1` 本地 only。

**Server 启动假设**:`uv run python -m dashboard.server`(详 § 8.3 启动方式)。

### § 6.7 UI Layer · htmx

- htmx 1.x vendored 到 `static/htmx.min.js`(无 npm)
- CSS 单文件手写在 `static/style.css`(无 tailwind / 框架)
- Jinja2 partial 模式:tab 切换 / filter 触发 → htmx GET partial 替换主区
- 编辑模式 toggle 通过 htmx form post 即时落库,无 reload

---

## § 7 视图布局

### § 7.1 主视图 (`/`)

```
┌──────────────────────────────────────────────────────────────┐
│ Hero (固定一行 60px)                                          │
│ 📅 2026-05-07 周五 | wip: [04 Long-term] [07 A/B Testing]   │
│                                          [刷新] [编辑模式]   │
├──────────────────────────────────────────────────────────────┤
│ Tab: [D 维度视图]  [B Kanban]                                 │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│ (D 视图 default · 8 layer 卡 2x4 grid · 详 § 7.2)            │
│ (B Kanban toggle · 三列 · 详 § 7.3)                          │
│                                                              │
├──────────────────────────────────────────────────────────────┤
│ 09 App Shell · FE 70% · BE 80% · Auth 100% · DB 100% · Conn 100% · Infra 60% │ (虚线灰)
└──────────────────────────────────────────────────────────────┘
```

**Hero 一行内容**:
- 左:`📅 YYYY-MM-DD · 周X`(实时,从服务端拿当前日期)
- 中:`当前 wip:` + chip 列表(每 chip = `[XX] capability 中文名`,点击 anchor 跳到该 layer 卡)
- 右:`[刷新]`(POST /refresh) + `[编辑模式]`(toggle,本地 cookie 状态)
- **wip 为 0 时**:显示 `今天没在做任何 capability — 从 todo 挑一个?`(引导)

### § 7.2 D 维度视图(default)

8 个 layer 卡(2×4 grid),每卡:

```
┌────────────────────────────────────┐
│ 04                          5/8    │ ← 编号 + lit/total
│ 记忆层 · Memory                     │ ← 中英名(中文为主 + 英文括注)
│ ──────────────────────────────     │
│ ✅ Session       ✅ Cassette state │ ← lit chip(实色绿)
│ 🟠 Long-term  [→ Done]            │ ← wip chip(实色橙) + 快捷按钮
│ ⬜ Semantic      ⬜ Cross-user      │ ← todo chip(虚线灰)
│ ⬜ ...                             │
└────────────────────────────────────┘
```

**编辑模式**(右上 toggle 开启):
- 点 todo chip → 弹小菜单 `[→ Doing]` `[→ Done force-lit]`
- 点 wip chip → 弹小菜单 `[→ Done]` `[→ Todo 撤回]`
- 点派生命中的 lit chip → 灰色不可改(grep 命中,改不了根本状态)
- 点 force-lit override 的 lit chip → 弹 `[→ Todo 撤回 override]`

**chip 数量超出卡片高度处理**:`overflow: auto` 内部滚动;每 layer 6-9 项实测不会溢出,留为 v2 体感问题。

### § 7.3 B Kanban 视图(toggle)

三列布局:

```
┌────────────┬─────────────┬─────────────┐
│ Todo (25)  │ Doing (2)   │ Done (35)   │ ← 折叠状态
├────────────┼─────────────┼─────────────┤
│ [04] Sem.. │ [04] L-term │ + 展开      │ ← Done 列默认折叠
│ [02] MCP   │ [07] A/B    │             │
│ [05] Rer.. │             │             │
│ [01] Ver.. │             │             │
│ ...        │             │             │
└────────────┴─────────────┴─────────────┘
```

**每张卡** = `[XX layer tag] capability 中文名 + 英文 mini`

**Done 列折叠规则**:default 折叠仅显示 `Done (35)` 计数 + `+ 展开` 按钮;点击后展开完整列表(35 张卡按 layer 编号排序)。

**编辑模式**:
- 点击卡片 → 弹菜单状态切换(同 § 7.2)
- 拖拽 v1 不实现(v2 候选,htmx + sortable.js 即可加)

### § 7.4 `/decisions` route(独立)

时间倒序决策列表:

```
2026-05-05 · v0.8.5 · [06 GUARD]
Constrained Router + 17-component skill bundle
  Why: prompt 漂移与 schema 软约束教训
  refs: 2026-05-05-v0.8.5-constrained-router-design.md
        commit b914dcb
  note: (用户备注)

2026-05-04 · v1 · [SCOPE]
砍 D2 本地化 (BGE/本地 LLM)
  Why: 本地硬件受限
  refs: project_v1_d2_dropped.md
  note: (用户备注)

...(更多)
```

**顶部 filter**:
- `layer chip` 多选(01-08 + SCOPE/META 等)
- `state` 多选(active / 砍 deprecated)
- 关键字搜索(client-side filter,无 server roundtrip)

**派生来源**:
1. `memory/feedback_*.md` `memory/project_*.md` 的 frontmatter(name + description + type)
2. spec 中 `## §.* 决策一/二/三:` 节段(正则 `^## § \d+ 决策`)

**决策稳定 ID**:`sha256(version + layer + title)[:12]` —— 同一决策跨刷新 ID 不变;内容修改后 ID 应变化(以触发 re-note)。

**编辑模式**:每决策卡可设 `note`(用户备注)。**无 approved 字段**(没公开页,无语义)。

---

## § 8 工程组成

### § 8.1 目录结构

```
dashboard/                       # 顶级目录,跟 backend/ frontend/ 平级
├── __init__.py
├── server.py                    # Starlette app + 路由 (~ 150 LoC)
├── derive/
│   ├── __init__.py
│   ├── capability_resolver.py
│   ├── decision_extractor.py
│   ├── path_router.py
│   └── snapshot_builder.py
├── state/
│   ├── __init__.py
│   ├── db.py                    # sqlite schema + connection
│   └── repositories.py          # 3 表 CRUD
├── templates/
│   ├── base.html                # Jinja2 base
│   ├── main.html  decisions.html
│   ├── _hero.html  _d_view.html  _b_view.html  _decision_card.html
├── static/
│   ├── htmx.min.js              # vendored, 无 npm
│   ├── style.css                # 单文件手写
│   └── icons.svg
├── config/
│   ├── capabilities.yaml        # 60 项 capability + derive_rule
│   └── dimensions.yaml          # 8 维 layer + path routing
└── tests/
    ├── derive/
    │   ├── fixtures/
    │   │   ├── sample_specs/  sample_memory/  sample_code/  sample_git_log.txt
    │   └── golden/
    │       ├── expected_capabilities.json  expected_decisions.json
    ├── state/
    └── server/
```

### § 8.2 依赖追加

只新增 2 个依赖到 backend pyproject:

```toml
[project.dependencies]
# ... 现有 deps
jinja2 = "^3.1"          # Starlette templates
pyyaml = "^6.0"          # capabilities.yaml 解析
```

复用栈:
- **Starlette**:FastAPI 底层已装(`from starlette.applications import Starlette`)
- **sqlite3**:Python stdlib
- **htmx**:vendored .js,无 python dep
- **CSS**:手写,无 tailwind / 框架

**memory `feedback_dev_tool_version_pin_alignment`**:新增依赖必须 align pyproject + pre-commit + uv.lock,实施时统一在一个 PR 内。

### § 8.3 启动方式

```makefile
# Makefile (top-level)
.PHONY: board board-stop board-refresh

board:
	uv run python -m dashboard.server &
	@sleep 1 && open http://localhost:8910

board-stop:
	pkill -f "python -m dashboard.server" || true

board-refresh:
	curl -sX POST http://localhost:8910/refresh && echo " ✓ refreshed"
```

**端口 8910**:跟产品 backend 8000 + frontend 5173 错开。

**python -m 路径策略**(memory `feedback_python_m_path_dual_context`):
- 启动命令 `uv run python -m dashboard.server` from project root
- `dashboard/__init__.py` 让其成为 package
- backend 模块通过 `from app.services.xxx import ...` 路径在 `dashboard/derive/*.py` 内访问(因 backend 是 source root,模块名是 `app.*`)
- **sys.path 注入放 `dashboard/__init__.py`**(不是 `server.py`),保证 pytest 跑 derive 测试时也生效:
  ```python
  # dashboard/__init__.py
  import sys
  from pathlib import Path
  _BACKEND_ROOT = Path(__file__).parent.parent / "backend"
  if str(_BACKEND_ROOT) not in sys.path:
      sys.path.insert(0, str(_BACKEND_ROOT))
  ```

### § 8.4 capabilities.yaml 格式(单一真源)

```yaml
# dashboard/config/capabilities.yaml
dimensions:
  - id: prompt_context
    number: "01"
    name_cn: "提示与上下文"
    name_en: "Prompt & Context"
    color: "#a78bfa"
    capabilities:
      - id: multi_tier_signature
        name_cn: "多层级签名"
        name_en: "Multi-tier signature"
        derive_rule:
          type: code_grep
          pattern: 'def chat\(.*tier:'
          path_glob: 'backend/app/services/llm_*.py'

      - id: skills_bundle
        name_cn: "Skills bundle"
        name_en: "Skills bundle (17-component)"
        derive_rule:
          type: file_exists
          path: 'backend/app/services/skills/registry.py'

      # ... 8 项 / layer 共 ~ 60 项 + App Shell 6 项
```

---

## § 9 MVP 分期 + 测试策略

### § 9.1 3 期 ship,3-5 天 wall time

| 期 | 内容 | 量级 | ship 标准 |
|---|---|---|---|
| **M1** | Source + Derive(capability_resolver + path_router) + State(snapshot/override 表) + Server 骨架 + D 视图(只读) + Hero | 1.5-2 天 | `make board` 浏览器看到 D 视图,8 layer 卡片 + capability chips 三态显示,无编辑无 toggle;首屏 lit 35 / total 60 与 § 3.2 anchor 一致 |
| **M2** | B Kanban toggle + 编辑模式(wip 切换 + force-lit/force-todo override) + 09 App Shell 第 9 行 | 1-1.5 天 | 切 B Kanban 看三列;编辑模式 toggle wip,关浏览器再开仍在;09 App Shell 6 项 mini stat 显示 |
| **M3** | `/decisions` route + decision_extractor + filter UI | 1 天 | /decisions 列表显示 memory + spec 决议(预计 ~ 30-50 项);layer/state 多选 filter 工作;关键字搜索 client-side 工作 |

**M1 解决 A + C(早上启动 + 全貌)** → **M2 让 B(优先级)+ wip 语义跑起来** → **M3 满足 D(决策追溯)**(不阻塞日常使用)。

### § 9.2 工期前提

- 每天 4-5h Claude Code 投入(memory `feedback_estimate_in_claude_code_walltime`)
- 周末加倍
- 假设无 cassette 重录(本工具不调 LLM)
- 假设 Starlette + Jinja2 + htmx 第三方 plugin 默认行为已在 spike 阶段实测(memory `feedback_third_party_plugin_defaults`)

### § 9.3 测试策略

#### § 9.3.1 Derive 层 golden 模式(沿用 v0.5/v0.7 范式)

```
dashboard/tests/derive/
├── fixtures/
│   ├── sample_specs/       # 冻结的 spec markdown 子集
│   ├── sample_memory/      # 冻结的 memory frontmatter 子集
│   ├── sample_code/        # 冻结的 backend code 子集
│   └── sample_git_log.txt
└── golden/
    ├── expected_capabilities.json
    └── expected_decisions.json
```

每次派生层改动必须:
1. 跑 `uv run pytest dashboard/tests/derive` → 对比 golden,任何 diff fail
2. 如确定要改 golden:`uv run pytest --update-golden` 重生成 + commit + 在 PR 描述写"派生 golden 更新原因"

#### § 9.3.2 State 层 sqlite CRUD smoke

- `capability_override`:set / get / clear
- `decision_tags`:set note / clear
- `derived_snapshot`:overwrite / read latest

#### § 9.3.3 Server 层 endpoint smoke

- `GET /` 200 + Jinja render 不报
- `GET /decisions` 200 + filter querystring 解析
- `POST /wip-toggle` 200 + DB 状态变 / 422 非法 capability_id
- `POST /refresh` 200 + 派生 cache 重建(snapshot.refreshed_at 更新)
- `GET /partials/d-view` 200 + Jinja partial(htmx 触发)

#### § 9.3.4 E2E

跑当前项目真实数据做一次完整 derive → 验证:
- 不报错 / 不空 / 覆盖所有 layer
- lit / total 计数与 § 3.2 anchor 一致(回归保险)
- App Shell 6 项都能识别到至少 1 个 commit

#### § 9.3.5 不做的(YAGNI 自用工具)

- ❌ E2E browser test(自动化点击 chip)
- ❌ Visual regression(snapshot)
- ❌ 鉴权 / RBAC / 多用户
- ❌ Rate limit / 429 处理

---

## § 10 范围边界 / YAGNI

### § 10.1 在范围内 ✓

1. D 维度视图(8 维 + App Shell 第 9 行 catch-all)
2. B Kanban toggle 视图(三列 todo/doing/done)
3. Hero 一行(今日日期 + 当前 wip chip + 刷新/编辑按钮)
4. 编辑模式(wip toggle + force-lit/force-todo override)
5. `/decisions` 独立 route(memory + spec 决议派生 + 个人 note)
6. 半自动维护(grep 派生 lit/todo + 手填 wip)
7. `capabilities.yaml` 单一真源(62 项初版)
8. 本地 only(`127.0.0.1:8910`)

### § 10.2 不在范围 ✗(显式排除,防滑动)

| 砍掉 | 来源 |
|---|---|
| ❌ 公开页 / portfolio 模式 | brainstorming Q2 仅自用 |
| ❌ Status Dashboard 数字 hero | brainstorming Q6a 选 C 今日聚焦 |
| ❌ Roadmap Timeline / Matrix 视图 | brainstorming Q1 没选 C |
| ❌ Narrative Wiki 叙事页 | brainstorming Q1 没选 E |
| ❌ 跨维度依赖追踪图 | 用户痛点未撞 B |
| ❌ Cost / test pass / commit / blocker 边角 | brainstorming Q6c 默认全砍 |
| ❌ approve flag(decisions) | § 7.4 决议 — 无公开页无语义 |
| ❌ 真实时 file-watcher | lazy 派生 + cache 够 |
| ❌ 多用户 / 协作 / RBAC / 鉴权 | 本地 only |
| ❌ Mobile 端 / 响应式 | 浏览器内 1280px+ |
| ❌ E2E browser test / Visual regression | YAGNI 自用工具 |
| ❌ npm / 前端框架(React/Vue/Tailwind) | htmx vendored + CSS 手写 |
| ❌ GitHub Actions / CI 直连 | 留 v2 看是否撞痛点 |
| ❌ 自动 LLM 周报 / 总结 | YAGNI |
| ❌ 嵌入 backend `/api/*` 路由 | 独立工具,不污染 backend `pytest` surface |

### § 10.3 与现有项目的依赖关系

- **强依赖**:无(独立工具,不阻塞主线)
- **弱依赖**:backend uv venv(共享 deps + 新增 jinja2/pyyaml)+ `memory/*.md` + `docs/superpowers/specs/*.md` + git history(项目 baseline 已有)
- **不阻塞**:dashboard 实施期间 v0.9.x / v1.0 主线继续推进不受影响
- **建议启动时机**:任何时候(独立工具不阻塞 v0.9.x ship);推荐 v0.9.x ship 后立即跑,第一次就有 35/60 baseline

### § 10.4 后续 v2 候选(显式标注不进 v1)

- 决策卡 approved 公开 flag(若将来想做 portfolio)
- GitHub Actions / commit 频率派生
- Cost trend 可视化(若撞到痛点)
- 跨维度 drift 警报(若撞到痛点)
- 自动 LLM 周报生成
- B Kanban 拖拽切换状态(htmx + sortable.js)
- 嵌入产品 frontend 的 `/admin/board` 路由(如果产品需要)

---

## § 11 业界对齐说明

简历级别引用"我做了完整 8 维 LLM Harness"时,业界共识对照(防被反驳):

| 我们的 | 业界主流命名 | 标志性产品 / 文献 |
|---|---|---|
| 01 Prompt & Context | Prompt Engineering / Context Engineering | Anthropic Skills bundle / OpenAI Cookbook / DAIR.AI guide |
| 02 Tools & Function Calling | Tool Use / Function Calling / Actions | **MCP**(Model Context Protocol)/ OpenAI Functions / Anthropic Tools |
| 03 Orchestration / Multi-Agent | Agent Orchestration / Workflow | **LangGraph** / CrewAI / AutoGen / Anthropic Subagents |
| 04 Memory | Memory(短期 / 长期 / 语义) | **Letta**(原 MemGPT)/ mem0 / LangChain Memory |
| 05 RAG / Knowledge | Retrieval / Vector / Knowledge | LlamaIndex / Pinecone / Weaviate / Chroma |
| 06 Guardrails & Auto-Repair | Guardrails / Safety / Validation | **NVIDIA NeMo Guardrails** / Pydantic AI / Constitutional AI(Anthropic) |
| 07 Eval & Observability | Eval / Tracing / Monitoring | **LangSmith** / Helicone / Arize / Phoenix / Weights & Biases |
| 08 Cost & Routing | Cost / Caching / Model Routing | **Portkey** / NotDiamond / Martian / Helicone |

**报告级别 anchor**:
- a16z 2024 **AI Stack** 报告(8 层划分,本 spec 6 层重合)
- Sequoia **Generative AI Stack**
- LangChain **conceptual layers** 文档
- **MCP** 把 Tools/Resources/Prompts 单独提层

**业界没共识但本 spec 选择的归并**:
- "Prompt Versioning" 合并进 01(有些公司单独提层)
- "Streaming / UX" 归 App Shell(有些公司单独提层)
- "Auth / Multi-tenant" 归 App Shell(SaaS 才独立)

---

## § 12 Open Questions(implementation 阶段决定)

以下问题不影响 spec 完整性,但 implementation 阶段需要敲定:

1. **派生层缓存策略**:每次刷新全跑(慢但简单)vs 增量(快但复杂)。推荐 M1 全跑,M2 看实测时间决定是否做增量(62 项 grep + ~30 决策提取,预计 < 1s,可能不需要增量)。

2. **Capability yaml 演化追踪**:capability 清单本身的演化怎么追?yaml diff 进 git history(推荐)还是单独"capability schema 版本"?推荐 git 即可。

3. **App Shell 6 项的派生公式**:FE/BE 显示百分比怎么算?candidate:lit capability hit ratio / file count / loc。实施时各项独立决定,在 dimensions.yaml 写公式参数。

4. **Capability override 的 drift 检测**:作者手动 force-lit 一项,但代码里 grep 早已能命中——是不是该提示"override 已多余,可删"?推荐 M2 加这个 hint。

5. **htmx 1.x vs 2.x 选型**:1.x 稳定 + 文档完整;2.x 新出。推荐 1.x(spike 后可改)。

6. **Starlette TestClient 引入测试**:Server 层 endpoint smoke 用 `starlette.testclient.TestClient` 还是 `httpx.AsyncClient`?推荐前者(stdlib 风格)。

7. **首次启动 `derived_snapshot` 为空怎么处理**:M1 加首次访问 lazy 派生(若 snapshot 为空则 sync derive 一次);避免 `make board` 后白屏。
