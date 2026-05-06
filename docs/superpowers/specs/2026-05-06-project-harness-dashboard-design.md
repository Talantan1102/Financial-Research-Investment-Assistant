# 项目 Harness Dashboard Design Spec

**作者**:Talantan1102
**起草**:2026-05-06
**状态**:Spec 已对齐;v0.9.0 / v0.9.x 收尾后启动 implementation
**类型**:Internal tooling spec(进 writing-plans)

---

## § 0 元信息与范围

本 spec 承载 **项目 Harness Dashboard** 的设计决策,对应一个**横跨 v0.9~v1.x 的开发者元工具**(meta-tool):一个嵌入现有 frontend 的 dashboard,用 8 维 LLM Harness 视角追踪项目能力点亮状态,辅以决策档案与卡点视图,长期跟进开发全流程。Brainstorm session 在 2026-05-06 完成。

**触发动机**:作者明确表达"虽然有 roadmap 但缺少把控感"——项目跨前/后/库/算/运多维度,markdown 形式的 spec/plan/memory 资产已积累 40+ 篇,但**没有一个聚合视图能一眼看到**:
- 当前在哪个 milestone(spec/plan 散落)
- 优先级该挑哪一个 epic(9 个独立模块都"想做")
- 全局完成度(无 Bird's-eye view)
- 关键决策的归档(分散在 memory + spec + commit message)

进一步对话暴露出**视角层面的关键转向**:用户最初按"前端/后端/数据库/算法/运维"切维度,经讨论后认知到**这个项目本质是 LLM harness 工程**,应当用业界共识的 LLM 应用栈维度(Prompt/Tool/Orchestration/Memory/RAG/Guardrail/Eval/Cost)切片,而非应用工程视角。这一转向直接对齐求职定位"LLM 应用算法+infra"。

**前置 spec 引用**:
- `2026-05-05-v0.9+-roadmap-and-long-running-task-scheduling.md`(§ 2 阶段图 + § 6 brainstorm 队列,本 spec 是 § 6 队列的一员,但因横跨多 milestone 的工具属性,独立成 spec)
- `2026-05-06-v0.9.x-frontend-rebuild-design.md`(本 spec UI 嵌入现有 frontend,前端重构 ship 是本 spec implementation 的前置)
- `2026-05-05-v0.8.5-constrained-router-design.md`(Skills bundle / plan_registry / ToolRegistry 是 8 维 harness 的"02 Tools" / "06 Guardrails"层 capability 来源)

**关键 memory 引用**:
- `user_portfolio_target` — 求职定位:LLM 应用算法+infra,每个非平凡决策需带 alternatives/tradeoff/量化评估
- `feedback_design_doc_format` — 四件套格式:问题陈述 + 业界 alternatives + tradeoff + 量化评估方案
- `feedback_no_portfolio_simplification` — 不能用 portfolio 借口降低技术严谨度
- `feedback_estimate_in_claude_code_walltime` — 工期按 Claude Code wall time 算
- `feedback_plain_language_for_industry_terms` — 业务讲述用大白话(本 spec 内技术术语保留英文,但解释段落用中文)
- `project_v1_product_positioning_broad` — 通用金融 agent 平台,本 dashboard 服务于"平台叙事"
- `project_v1_route_product_first` — Product-first;不预先抽象未提交需求(本 spec 砍跨维度依赖追踪等未撞痛点的特性)
- `feedback_unguarded_imports_after_delete` — 删除型 task 必须 grep 守护(派生层可能涉及现有路径变化)

**不在范围**(YAGNI 边界):
- 跨维度依赖图(用户当前没撞到 "改算法导致前端断" 这种痛,不实现)
- 自动 LLM 总结/讲解(诱人但非必需,留 v2)
- 多用户协作(单作者项目)
- 真实时 file-watcher(手动 + pre-commit hook 触发够了)
- 通用项目支持(只服务 financial-research-assistant 项目,不做开源,不抽象)
- Gantt 图 / 资源调度(不是项目管理软件)
- PR 列表 / CI 健康度直连 GitHub API(留 v2)
- 真实时协作(WebSocket / multi-cursor)
- 移动端(桌面优先,浏览器内 1280px+ 设计)

---

## § 1 痛点诊断:为什么现在做

Brainstorm Q1 阶段定位"把控感缺失"的 5 个候选病因,作者明确选中 **A + C + D + E**(B 跨维度依赖目前未撞痛,留口子不实现):

| 病因 | 描述 | 命中 |
|---|---|---|
| **A 当前阶段失焦** | v0.9 多 epic,切换时容易"忘了上次进行到哪、下一步是什么" | ✓ |
| B 跨维度依赖看不见 | 算法改 → 后端契约 → 前端 → DB schema 漂移 | ✗ |
| **C 优先级模糊** | 9 个独立模块每个都想做,不知道现在挑哪个 | ✓ |
| **D 全局完成度看不见** | 想一眼看到"v1 大概到哪了"或"Memory 层做到哪了" | ✓ |
| **E 历史决策追溯难** | "为什么砍了 D2"/"百炼切换的原因",要翻 memory + spec + commit | ✓ |

**ACDE 共同特征**:都是"全局 / 当前位置 / 历史"的可视化诉求,而非"任务流 / 协作"诉求。这决定了 dashboard 形态偏 **静态俯瞰图 + 决策档案**,不是 Kanban/Trello。

**ACDE 的工具诉求映射**:
- A → 当前 milestone 卡 + 下一步动作
- C → 各 harness 维度的"已点亮 / 待做"对比 → 推导优先级("Memory 1/6 是最弱项 → v1.0 重点开发")
- D → 8 维 harness Capability Matrix(35/60 这种聚合数)+ App Shell catch-all 行
- E → 决策日志侧栏(timeline + layer 标签 + 公开/私有/砍掉三态)

**为什么是"现在"而不是更早做**:
- v0~v0.8.5 期间作者是"晚上在场全程值守"工作模式,markdown spec + memory 已经够用
- v0.9+ 进入"白天通勤异步开发 + 9 模块并行"阶段,markdown 索引方式开始失效
- v0.8.5 已 ship,资产积累 40+ spec/plan/memory,**有足够数据被聚合可视化**(早做没数据)

---

## § 2 视角:8 维 LLM Harness + App Shell catch-all

### § 2.1 决策:用 LLM Harness 视角切片,不用应用工程视角

**问题陈述**:维度怎么切?用户最初直觉是"前端/后端/数据库/算法/运维"5 维,这是工程师按代码归属的视角。但这种视角在 LLM 应用项目中会**把简历亮点(prompt/agent/memory/RAG/eval)藏在"算法"一格里看不见**,Memory 层未做的 5 项 capability 也被 backend 70% 平均掉。

**业界 alternatives**(2024-2025 LLM 应用栈共识):

| 切法 | 来源 | 适用 |
|---|---|---|
| **LLM Harness 8 维(选用)** | a16z AI Stack / Sequoia GenAI Stack / LangChain conceptual layers / MCP 协议 | 单作者 LLM portfolio |
| 应用工程 5-7 维(FE/BE/DB/Algo/DevOps/...) | 通用软件项目 | 多人团队 + 非 LLM 主轴 |
| 研发职能切法(PM/Design/QA/SRE) | 大型公司 | 多职能团队 |
| DDD 用户价值流(按业务域) | 大型 SaaS,多业务线 | 多产品线 |
| FURPS 质量属性(Functionality/Reliability/...) | SLA 重产品(支付/医疗) | 不适用 |

**Tradeoff**:

| 视角 | 优 | 劣 |
|---|---|---|
| **LLM Harness 8 维** | 简历叙事 1:1 对齐 LLM 工程师 JD;每条泳道天然有"已有 + 待做";平台叙事一致 | 应用层"前端/Auth"无主泳道(下沉到 App Shell catch-all) |
| 应用工程 5-7 维 | 直觉对齐文件结构;看代码归属直接 | LLM 亮点被压缩;Memory 缺口被平均掉看不见 |

**量化评估**:

- 简历对齐度:8 维和 LLM 工程师典型 JD 关键词重合度 ~85%,5 维重合度 ~30%
- 弱项暴露度:8 维下 Memory(1/6 lit)是显眼弱项,5 维下 Memory 被 Backend(70%)淹没
- 学习曲线:8 维需要作者熟悉业界术语,作者已熟悉(memory 中多次出现 LangGraph/Send/subgraph/critic 等),无成本

**选用 8 维 LLM Harness 视角,App Stack 视角不做**(brainstorming Q5 用户明确砍掉 toggle 切换,简化为单一视角)。

### § 2.2 8 个 Harness 维度定义

每个维度对应业界共识的 LLM 应用栈层。命名遵循 § 7 中英混排原则:中文为主标题 + 英文括注。

| # | 中文名 | English | 业界对应 |
|---|---|---|---|
| **01** | 提示与上下文 | Prompt & Context | Anthropic Skills / OpenAI Cookbook |
| **02** | 工具与函数调用 | Tools & Function Calling | MCP / OpenAI Functions / Anthropic Tools |
| **03** | 编排与多智能体 | Orchestration / Multi-Agent | LangGraph / CrewAI / Anthropic Subagents |
| **04** | 记忆层 | Memory | Letta / mem0 / LangChain Memory |
| **05** | 检索增强 | RAG / Knowledge | LlamaIndex / Pinecone / Weaviate |
| **06** | 护栏与自修复 | Guardrails & Auto-Repair | NeMo Guardrails / Pydantic AI / Constitutional AI |
| **07** | 评测与可观测 | Eval & Observability | LangSmith / Helicone / Arize / Phoenix |
| **08** | 成本与路由 | Cost & Routing | Portkey / NotDiamond / Martian |

**业界对齐说明详见 § 10**。

### § 2.3 App Shell catch-all(09)

8 维 harness 之外,**应用层工程完整性**(Frontend / Backend / Auth / Database / Connectors / Infra)不另开主泳道,**压缩为底部一行 mini stat**:虚线边框、灰调、单行 percentage。

**为什么不放主泳道**:
1. 这些是工程基线(任何 web 应用都需要),不是 LLM harness 的差异化亮点
2. 在主泳道中会**稀释 harness 维度的视觉权重**(简历主轴被淹没)
3. 仍需保留(单纯不显示会看不见"工程完整性"维度)

**App Shell 6 项**:
- 前端 Frontend
- 后端 Backend
- 鉴权 Auth
- 数据库 Database
- 外部数据 Connectors(tushare/bocha/milvus 客户端层,但 corpus/retrieval 算 RAG)
- 部署 Infra/CI

---

## § 3 Capability Matrix 数据模型

### § 3.1 决策:用 Capability Matrix 替代 Progress Bar

**问题陈述**:每条 harness 泳道用什么"完成度指标"?用户首版 mockup 看到"Memory 15%、AI 82%"等百分比后明确反馈:**"进度条感觉很鸡肋,因为每个维度永远都有可以优化的地方"**。

**业界 alternatives**:

| 指标 | 描述 | 业界示例 |
|---|---|---|
| **Capability Matrix(选用)** | 每层若干离散 capability,状态 = 已点亮 / 进行中 / 待做 | OWASP Maturity Model / MLOps maturity Level 0-4 / Anthropic Skills 计数 |
| Percentage(派生百分比) | 完成 task / 总 task | 通用 PM 软件 |
| Maturity Level(等级模型) | Level 0-5,每级有清单 | MLOps maturity / CMMI |
| Capability score(加权分) | 每 capability 有权重 + 0-10 评分 | 内部能力评估 |

**Tradeoff**:

| 指标 | 优 | 劣 |
|---|---|---|
| **Capability Matrix** | 无虚假"完成度"暗示;具体能力点显眼;简历能直接拷贝点亮项 | 需要作者维护 capability 清单(配置文件半手动) |
| Percentage | 直观一目了然 | LLM harness 没有"完成"概念;Memory 永远可以做更深;弱项被平均掉 |
| Maturity Level | 业界已知模型 | 离散等级粒度太粗(L1/L2 之间巨大跳跃) |
| Capability score | 量化精细 | 评分主观;权重难定 |

**量化评估**:

- 信息密度:Capability Matrix 每屏显示 60+ 具体能力点,百分比每屏 8 个数字
- 简历可拷贝度:Capability Matrix 直接能拷贝"已点亮 LangGraph + Send + subgraph + 7-stage Critic"作为 bullet,百分比无法拷贝
- 维护成本:Capability Matrix 需要 yaml 配置(每层 6-9 项),百分比由 task 数自动算
- 弱项识别:Capability Matrix 04 Memory(1/6)→ v1.0 重点;百分比下 Memory 被淹没

**选用 Capability Matrix**。维护成本(yaml)是一次性的,业界 best practice 出新 capability 时手动追加(年度级别频率)。

### § 3.2 Capability 数据模型

```yaml
# dashboard/capabilities.yaml
# 每个 harness 维度的 capability 清单 + 状态推断规则

dimensions:
  - id: prompt_context
    number: "01"
    name_cn: "提示与上下文"
    name_en: "Prompt & Context"
    color: "#a78bfa"
    capabilities:
      - id: multi_tier_signature
        name_cn: "多层级签名"
        name_en: "multi-tier signature"
        status_rule:
          type: "code_grep"
          pattern: "def chat\\(.+tier:"
          path: "backend/app/services/llm_*.py"
          # 命中 → lit;未命中 → todo
      - id: constrained_schema
        name_cn: "输出 Schema 约束"
        name_en: "Constrained schema"
        status_rule:
          type: "code_grep"
          pattern: "schema:"
          path: "backend/app/services/llm_*.py"
      # ... 8 个 capability per dimension
```

**status_rule 类型**:
1. **`code_grep`**:在指定路径用正则 grep,命中 → lit
2. **`file_exists`**:某个文件存在 → lit
3. **`spec_section`**:某 spec 中有命名 section → lit
4. **`memory_frontmatter`**:某 memory frontmatter `version: vX.Y` → lit
5. **`manual`**:派生层不自动判定,完全手动 toggle(用于"自修复闭环 wip"这种语义判断)

### § 3.3 状态三态:lit / wip / todo

| 状态 | 颜色 | 派生规则 | 手填覆盖 |
|---|---|---|---|
| **lit 已点亮** | 绿 #14532d / #86efac | status_rule 命中 | 允许手动 force-lit(尽管 grep 没命中) |
| **wip 进行中** | 橙 #7c2d12 / #fdba74 | 仅 manual rule;或 status_rule 命中但有 work-in-progress 标记 | 全手动 |
| **todo 待做** | 灰 #1e293b dashed border / #64748b | 默认 | 自动状态 |

**手填覆盖规则**(B 半自动决策落地):
- 派生层每次刷新都重算 capability 状态
- 状态 = `derived_state` UNLESS `manual_override` 存在
- `manual_override` 存表 `handfill_capability_override(capability_id, status, reason, set_at)`,作者在编辑模式可设
- override 永久有效直到作者手动清除(派生层不擦除手填)

### § 3.4 Capability 总数 anchor

**初始 capability 清单**(60 项,首版):

| Layer | Lit count | Total | 已有(lit) |
|---|---|---|---|
| 01 Prompt & Context | 4 | 8 | multi-tier signature / constrained schema / Skills bundle (17) / per-task registry |
| 02 Tools & Function Calling | 5 | 8 | Tool Registry / Schema-validated I/O / DI mock-real / Reliability layer / 8 financial tools |
| 03 Orchestration / Multi-Agent | 6 | 9 | LangGraph / 5 agents / Send + subgraph / 7-stage Critic / SSE / SqliteSaver |
| 04 Memory ⚠ | 1 | 6 | session (SqliteSaver) |
| 05 RAG / Knowledge | 5 | 8 | Milvus 3 collection / embedding + cache / 13 corpus / Bocha web / reliability |
| 06 Guardrails & Auto-Repair | 4 | 7 | Constrained Router / Pydantic schema / LangGraph retry / per-step Critic |
| 07 Eval & Observability | 6 | 9 | EvalRunner / TraceService / LLM-as-Judge / 12 golden / Cassette / 289 tests |
| 08 Cost & Routing | 4 | 7 | Tier Router / Pricing / Cost budget / max_tokens calibration |
| **Total** | **35** | **60** | |

**待做 25 项**(detail per dim 见 mockup):构成 v0.9~v1.x 的 backlog 主轴。

---

## § 4 架构:5 层

### § 4.1 决策:嵌入现有 frontend + B3 双形态

**问题陈述**:dashboard 工程形态怎么选?独立微服务 vs 嵌入现有 frontend vs Markdown 生成?

**业界 alternatives**:

| 形态 | 描述 | 与产品代码关系 |
|---|---|---|
| 独立微服务 | `dashboard/` 目录 + Python http.server + htmx + sqlite | 零耦合 |
| **嵌入现有 frontend(选用)** | React Admin 路由 + backend `/api/dashboard/*` | 与产品共栈 |
| Markdown + 静态站 | `make dashboard` 生成 HTML | 极简但不可手填(与 B 半自动冲突,被否) |

**Tradeoff**:

| 形态 | 优 | 劣 |
|---|---|---|
| 独立微服务 | 零耦合;极简栈;不污染产品测试 | 多一个 service 维护;无 portfolio 物料价值 |
| **嵌入现有 frontend(B3)** | 复用 React 栈;**可作为 portfolio 物料**;public 投影暴露价值 | 与产品耦合;React SPA 复杂度比 htmx 高 ~50%;影响产品测试 surface |
| Markdown + 静态站 | 极简;无 build | 不能手填;与 B 半自动维护冲突 |

**量化评估**:

- 工程量级:独立微服务 ~6-8 天;**嵌入 + B3 双形态 ~9-13 天**(含 admin / public + 脱敏投影 + 4 期 ship);Markdown 3-4 天但功能降级
- 简历价值:独立微服务低;**嵌入 + 公开页给面试官看价值高**;Markdown 几乎无
- 维护风险:嵌入 frontend 有 1 个新 router 需维护,但**复用 auth/SSE/component**,实际增量低

**选用嵌入现有 frontend + B3 双形态**(brainstorming Q4 用户选 B,Q5 用户接受 B3 默认双形态推进)。

**B3 双形态语义**:
- `/admin/dashboard`(B1 内部):全数据,登录鉴权(沿用 frontend 现有 auth)
- `/dashboard`(B2 公开):脱敏投影,readonly,可给面试官看
- 共享同一份派生快照,投影分流在 API 层

### § 4.2 5 层架构

```
┌─────────────────────────────────────────────────────────────┐
│ ① Source Layer · 只读现有资产                                  │
│   git history · docs/superpowers/specs · plans · memory/*.md │
│   backend/app/**(代码)· frontend/**(代码)                    │
└────────────────┬────────────────────────────────────────────┘
                 │ derive(纯函数 parser,可缓存)
                 ▼
┌─────────────────────────────────────────────────────────────┐
│ ② Derive Layer                                              │
│   dimension_classifier · milestone_assembler                │
│   capability_status_resolver · decision_extractor           │
└────────────────┬────────────────────────────────────────────┘
                 │ persist(全量替换 + 手填合并)
                 ▼
┌─────────────────────────────────────────────────────────────┐
│ ③ State Layer · sqlite at backend/data/dashboard.db        │
│   derived_snapshot · handfill_focus · handfill_blockers    │
│   handfill_capability_override · handfill_decision_tags    │
└────────────────┬────────────────────────────────────────────┘
                 │ FastAPI Router(prefix /api/dashboard)
                 ▼
┌─────────────────────────────────────────────────────────────┐
│ ④ API Layer · 复用 backend 进程 · 双投影                       │
│   /admin/* (full)  ◀── auth gate ──▶  /public/* (sanitized)│
└────────────────┬────────────────────────────────────────────┘
                 │ React Query hooks
                 ▼
┌─────────────────────────────────────────────────────────────┐
│ ⑤ UI Layer · React,挂在现有 frontend                          │
│   /admin/dashboard(B1)· /dashboard(B2)· CLI refresh        │
└─────────────────────────────────────────────────────────────┘
```

### § 4.3 Source Layer:数据来源 + 维度切分

**8 维 harness path/keyword routing**(配置文件 `dashboard/dimensions.yaml`):

| 维度 | 主路径 | 关键词(辅助) |
|---|---|---|
| 01 Prompt & Context | `backend/app/services/llm_*` `backend/app/services/skills/*` | "tier", "schema", "Skills" |
| 02 Tools & Function Calling | `backend/app/tools/**` `backend/app/services/tool_registry*` | "Protocol", "tool" |
| 03 Orchestration / Multi-Agent | `backend/app/agents/**` `backend/app/orchestration/**` | "LangGraph", "agent", "subgraph" |
| 04 Memory | `backend/app/services/memory_*` `backend/app/services/checkpointer*` | "Memory", "Saver", "checkpoint" |
| 05 RAG / Knowledge | `backend/app/services/{milvus,bocha,kb,corpus}_*` | "embedding", "retrieve" |
| 06 Guardrails & Auto-Repair | `backend/app/services/{constrained_router,critic,validator}_*` | "Schema", "Pydantic", "retry" |
| 07 Eval & Observability | `backend/app/services/{eval,trace,judge}_*` `backend/tests/**` | "EvalRunner", "TraceService", "Judge", "golden" |
| 08 Cost & Routing | `backend/app/services/{tier_router,pricing,cost_budget}_*` | "TierRouter", "pricing" |

**App Shell 9 行**:

| 维度 | 路径 |
|---|---|
| Frontend | `frontend/**`(除测试) |
| Backend | `backend/app/api/**` `backend/app/main.py` |
| Auth | `backend/app/api/auth_*` `frontend/**/Login*` |
| Database | `backend/app/**/db.py` `data/*.sql` schema |
| Connectors | `backend/app/services/{tushare,bocha,milvus}_client*` |
| Infra/CI | `docker*/**` `.github/**` `scripts/**` `pyproject.toml` |

**冲突解决**:文件命中多个 pattern 时,**更具体的优先**。规则配置在 `dashboard/dimensions.yaml`,人可读人可改。

**Memory 引用**:`feedback_unguarded_imports_after_delete` — 派生层删旧分类规则前必须 grep 守护被删 pattern 的 unguarded 引用。

### § 4.4 Derive Layer:4 个 parser 模块

```python
# dashboard/derive/dimension_classifier.py
def classify_path(path: str, dimensions_config: DimensionsConfig) -> DimensionId:
    """路径 + 关键词归类到 8 维 + App Shell;返回 dim_id 或 'unknown'"""
    ...

# dashboard/derive/milestone_assembler.py
def assemble_milestones(specs_dir: Path, plans_dir: Path) -> list[Milestone]:
    """读 spec frontmatter version/phase + plan checklist,返回 milestone 列表"""
    ...

# dashboard/derive/capability_status_resolver.py
def resolve_capability_status(
    capability: CapabilityConfig,
    code_index: CodeIndex,
    spec_index: SpecIndex,
    memory_index: MemoryIndex,
) -> CapabilityStatus:
    """按 capability.status_rule 类型分发到具体 resolver,返回 lit/wip/todo"""
    ...

# dashboard/derive/decision_extractor.py
def extract_decisions(memory_dir: Path, specs_dir: Path) -> list[Decision]:
    """从 memory feedback/project frontmatter + spec § 决议节段提取决策条目"""
    ...
```

**关键不变量**:派生层是**纯函数**——同样的 source layer 输入必产出同样的输出。这是 § 9 测试策略 golden 模式的基础。

### § 4.5 State Layer:sqlite 5 张表

```sql
-- backend/data/dashboard.db schema

CREATE TABLE derived_snapshot (
  id INTEGER PRIMARY KEY,
  refreshed_at TIMESTAMP NOT NULL,
  payload JSON NOT NULL  -- 全量派生快照,每次刷新替换
);
-- 仅保留最新一行,刷新时旧行删除(无历史保留)

CREATE TABLE handfill_focus (
  id INTEGER PRIMARY KEY,
  current_focus TEXT,
  next_action TEXT,
  updated_at TIMESTAMP NOT NULL
);
-- 单行表(只有 1 条),作者在编辑模式更新

CREATE TABLE handfill_blockers (
  id INTEGER PRIMARY KEY,
  text TEXT NOT NULL,
  severity TEXT NOT NULL,  -- 'warn' | 'blocked'
  created_at TIMESTAMP NOT NULL,
  resolved_at TIMESTAMP
);

CREATE TABLE handfill_capability_override (
  capability_id TEXT PRIMARY KEY,  -- e.g. "01.multi_tier_signature"
  status TEXT NOT NULL,  -- 'lit' | 'wip' | 'todo'
  reason TEXT,
  set_at TIMESTAMP NOT NULL
);

CREATE TABLE handfill_decision_tags (
  decision_id TEXT PRIMARY KEY,  -- 由 decision_extractor 输出的稳定 hash
  approved_for_public BOOLEAN DEFAULT 0,  -- B3 公开页投影开关
  user_note TEXT,
  set_at TIMESTAMP NOT NULL
);
```

**为什么 sqlite 不复用现有产品 DB**:
- 隔离风险:dashboard meta 数据不应进 production schema
- 迁移独立:dashboard schema 改动不触发 production migration
- 备份独立:dashboard.db 可单独 git ignore + 重建(数据可派生)

**为什么 sqlite 不用 JSON 文件**:
- 已有 sqlite 栈(SqliteSaver / TraceService),复用
- 多读少写场景 sqlite 更稳

### § 4.6 API Layer:双投影

```
GET  /api/dashboard/admin/overview     → 主视图聚合(全数据)
GET  /api/dashboard/admin/matrix       → 全局矩阵
GET  /api/dashboard/admin/timeline     → 时间线
GET  /api/dashboard/admin/decisions    → 决策日志
POST /api/dashboard/admin/focus        → 编辑 focus + next_action
POST /api/dashboard/admin/blockers     → 增删 blocker
POST /api/dashboard/admin/capability-override  → 手填 capability 状态
POST /api/dashboard/admin/refresh      → 触发派生重跑
POST /api/dashboard/admin/decision-approve  → toggle approved_for_public

GET  /api/dashboard/public/overview    → 主视图脱敏投影
GET  /api/dashboard/public/decisions   → 决策(只 approved_for_public=true)
```

**鉴权**:`/admin/*` 路由复用 frontend 现有 auth(JWT / session token)中间件;`/public/*` 完全开放。

**投影分流**:同一个 derived_snapshot 经过两个 Pydantic 投影模型:

```python
class AdminSnapshot(BaseModel):
    # 全字段
    current_milestone: Milestone
    dimensions: list[DimensionFull]  # 含具体 commit hash / file 路径
    decisions: list[Decision]  # 全部
    handfill_focus: FocusFull  # 含本周日记式 focus 文本
    blockers: list[Blocker]  # 含详细 text

class PublicSnapshot(BaseModel):
    # 字段白名单
    project_summary: ProjectNarrative  # 叙事化 hero
    dimensions: list[DimensionPublic]  # 仅 lit count + capability 名(无 commit hash)
    decisions: list[DecisionPublic]  # 仅 approved_for_public=true,且无 deprecated
    # NO focus / NO blockers / NO commit hash / NO file paths
```

**投影规则**(脱敏 allowlist):

| 字段 | Admin | Public | 说明 |
|---|---|---|---|
| 维度名 / capability 名 | ✓ | ✓ | 公开 |
| capability lit/total 计数 | ✓ | ✓ | 公开 |
| commit hash / 提交人 | ✓ | ✗ | 隐私 |
| file 路径 / 行号 | ✓ | ✗ | 隐私 |
| milestone version / ship 日期 | ✓ | ✓ | 公开 |
| ship 标准 detail | ✓ | ✓ | 简版 |
| handfill_focus 文本 | ✓ | ✗ | 日记性质 |
| blockers detail | ✓ | ✗ | 可能含敏感 |
| decisions title | ✓ | 仅 approved | 默认私有 |
| decisions why | ✓ | 仅 approved | 默认私有 |
| deprecated 决策 | ✓ | ✗ | 不展示 |

**默认 visibility = 私有**:`handfill_decision_tags.approved_for_public` 默认 `False`,作者在 admin 编辑模式手动 toggle approve。**默认安全原则** — 宁可少展示也不泄漏。

### § 4.7 UI Layer:React + 复用 design tokens

实施阶段强制 § 7 governance(必须 invoke `frontend-design` + `taste-skill`)。组件结构(初版 anchor,实施时由 skill 决定细节):

```
frontend/src/admin/dashboard/
  ├── pages/
  │   ├── AdminDashboard.tsx           # /admin/dashboard 入口
  │   ├── PublicDashboard.tsx          # /dashboard 入口
  │   └── views/
  │       ├── MainView.tsx             # 默认主视图
  │       ├── MatrixView.tsx           # 矩阵 toggle
  │       └── TimelineView.tsx         # 时间线 toggle
  ├── components/
  │   ├── HeroMilestone.tsx
  │   ├── HarnessLayerCard.tsx         # 一张 harness 维度卡(含 capability chips)
  │   ├── CapabilityChip.tsx           # lit/wip/todo 三态 chip
  │   ├── AppShellRow.tsx              # 09 catch-all 单行
  │   ├── FocusPanel.tsx
  │   ├── BlockersPanel.tsx
  │   └── DecisionLog.tsx              # 右栏 timeline
  ├── hooks/
  │   ├── useAdminOverview.ts          # React Query hook
  │   └── usePublicOverview.ts
  └── api/
      └── client.ts                    # axios / fetch wrapper
```

**实施时由 skill 决定的细节**(spec 不固化):
- 具体 className / styled-components / tailwind 选择
- 动画 / hover / transition
- 响应式断点
- 字体 / spacing tokens 与现有 frontend 对齐

**spec 固化的约束**(skill 必须遵守):
- 中英混排原则(§ 7)
- 9 维数据结构(§ 4.4)
- 3 态色彩语义(§ 3.3)
- 双形态字段差异(§ 4.6)

---

## § 5 视图组成

### § 5.1 主视图(默认)

```
┌──────────────┬────────────────────────────────────┬──────────────┐
│              │  Topline:Harness 状态 v0.9.x        │              │
│   Sidebar    │  Toggle: [主视图] 矩阵 时间线          │  决策日志     │
│              │                                    │  侧栏        │
│   - 视图       │  Hero: v0.9.x · 30% · ship 3/10    │              │
│   - 深入       │  ┌──────────┬──────────┐           │  Filter:     │
│   - 操作       │  │ 01 Prompt │ 02 Tools │           │  all/03/06...│
│              │  │ 4/8 lit   │ 5/8 lit  │           │              │
│              │  ├──────────┼──────────┤           │  ● v0.8.5    │
│              │  │ 03 Orch  │ 04 Mem⚠  │           │  ○ v0.8.4    │
│              │  │ 6/9 lit  │ 1/6 lit  │           │  ● 砍 D2     │
│              │  ├──────────┼──────────┤           │  ● v0.7      │
│              │  │ 05 RAG   │ 06 Guard │           │  ○ 百炼切换   │
│              │  │ 5/8 lit  │ 4/7 lit  │           │  ● v0.5      │
│              │  ├──────────┼──────────┤           │  ● v0 EVAL   │
│              │  │ 07 Eval  │ 08 Cost  │           │  ● v0 TOOLS  │
│              │  │ 6/9 lit  │ 4/7 lit  │           │              │
│              │  └──────────┴──────────┘           │              │
│              │  ─────────────────────────         │              │
│              │  09 App Shell · FE 40% BE 70%...   │              │
│              │  ─────────────────────────         │              │
│              │  📌 当前焦点  ⚠ Blockers (2)        │              │
└──────────────┴────────────────────────────────────┴──────────────┘
```

### § 5.2 矩阵视图(toggle)

8 维 harness × N milestones 网格,颜色编码 ✓ 已 ship / % 进行中 / · 规划 / — 不适用。点击单元格下钻进对应 spec/plan/commit。当前 milestone 用 ★ 标识。

### § 5.3 时间线视图(toggle)

纵向 milestone timeline,每个 milestone 节点展开:
- ship 日期 + ship 标准 checklist
- 该 milestone 期间点亮的 capability(harness layer 标签)
- 该 milestone 期间产生的决策

### § 5.4 公开页(`/dashboard`)

简化叙事化版本,**hero 是项目叙事而非 milestone 状态**:

```
┌─────────────────────────────────────────────────┐
│  AlphaScout · 通用金融 agent 平台                 │
│  首个落地 use case:投资尽调研报                   │
│  LangGraph 5-agent + 7-阶段 critic + Milvus KB │
│  v0.5 → v0.9.x · 2026-04 至今                    │
├─────────────────────────────────────────────────┤
│  能力维度成熟度:                                  │
│  01 Prompt 4/8 · 02 Tools 5/8 · ... · 08 Cost 4/7│
│                                                 │
│  关键技术决策(已审核公开):                        │
│  ✓ v0.8.5 7 阶段 Critic + Constrained Router    │
│  ✓ v0.7 Milvus + 13 真实 corpus                 │
│  ✓ v0.5 5-agent + Send API subgraph             │
│  ...                                            │
│                                                 │
│  脱敏覆盖:无 commit hash · 无 blocker · 无 focus  │
└─────────────────────────────────────────────────┘
```

---

## § 6 B3 双形态:rationale + 工程量增量

(已在 § 4.1 / § 4.6 详述,本节补充工程量评估。)

### § 6.1 增量工程量

| 项 | Admin only(B1) | Admin + Public(B3) | 增量 |
|---|---|---|---|
| 派生层 | 1 套 | 1 套(共享) | 0 |
| 状态层 | 1 套(共享) | 1 套(共享) | 0 |
| API 层 | 1 套 endpoint | 1 套 endpoint × 2 投影 | +30% LoC |
| Pydantic 投影模型 | 1 个 | 2 个(Admin / Public) | +1 model |
| UI 页面 | 1 页(/admin/dashboard) | 2 页(+ /dashboard 叙事化版) | +1 page |
| 测试(投影脱敏关键) | 标准 endpoint test | + AllowlistDriftTest | +1 重要测试 |

**B3 总增量 ~25-30%**,主要在 UI 层(public 页要叙事化重排)+ 1 个关键测试(allowlist drift)。

### § 6.2 关键测试:AllowlistDriftTest

新增字段时如果忘记决定它属于 Admin-only 还是 Public-also,**默认应该是 Admin-only**(默认安全)。但代码上要怎么强制?

**测试**:`test_public_snapshot_allowlist_drift.py` —— 用反射收集 `AdminSnapshot` 所有字段,逐一 assert 要么在 `PublicSnapshot.__fields__` 里,要么在 `KNOWN_ADMIN_ONLY_FIELDS` 显式名单里。新增字段会触发**测试失败**,作者必须明确决定该字段是否进 public。

这个测试是 portfolio 翻车防御 — 一个忘记脱敏的字段 = portfolio 信任损伤。

---

## § 7 UX 原则(含 Skill governance)

### § 7.1 中英混排原则

**规则**:

| 元素 | 写法 | 示例 |
|---|---|---|
| 主标题 / 按钮 / 说明 | 中文 | "📊 主视图" / "已点亮" |
| 维度名 | 中文 + 英文括注 | "**01 提示与上下文** `Prompt & Context`" |
| Capability chip | 中文描述 + 英文术语混排 | "**多层级签名** `multi-tier signature`" |
| 业界共识术语 | 保留英文 | `LangGraph` / `SSE` / `Tool Registry` / `Critic` / `Subgraph` / `Schema` / `Cassette` |
| 数字 / 版本 / 路径 | 英文等宽字体 | `v0.9.x · 35/60 · backend/data/dashboard.db` |
| 决策 layer 标签 | 英文短码 | `06 GUARD` `05 RAG` `08 COST` |

**Why**:
- 中文降低日常使用认知成本
- 英文术语保留业界识别度,简历可直接拷贝维度名英文部分
- 数字/路径/版本本身就是英文符号,等宽字体保持精度

### § 7.2 Design tokens 与现有 frontend 对齐

实施时**不允许新建 design tokens**,必须复用 `docs/design-tokens.md` + `frontend/src/styles/` 已有的 color / spacing / typography。

如发现现有 tokens 不够,实施期间必须先扩展共享 tokens(进 design-tokens.md),不能在 dashboard 专属 css 里写 magic value。

### § 7.3 Skill governance(hard rule)

**实施阶段所有 UI/前端任务必须 invoke skill,不允许自由发挥:**

| 任务类型 | 必须 invoke 的 skill |
|---|---|
| 任何 React 组件设计 / mockup 高保真化 | `frontend-design` |
| 任何 UI/UX 决策(组件架构 / CSS / 视觉 hierarchy) | `taste-skill` |
| Component 之间架构 | `taste-skill`(Senior UI/UX Engineer 视角) |

**Why**:
- 用户明确要求(2026-05-06 brainstorming Q9)
- skill 是"专业的",作者审美 + LLM 默认偏置都不如 skill 系统化
- skill 里强制了 metric-based rules / 组件架构 / CSS hardware acceleration 等工业级规范,自由发挥会漂

**violation handling**:implementation plan 里每个 UI/前端任务必须显式标注"调用 X skill"。skill 调用记录会被 PostToolUse hook 自动 log 到 `~/.claude/skills-log/{frontend-design,taste-skill}.jsonl`,review 时可审计。

### § 7.4 Capability chip 视觉规范(spec 固化)

实施阶段 skill 可决定排版细节,但以下 spec 固化不可改:

| 状态 | 必须满足 |
|---|---|
| **lit 已点亮** | 绿色背景(深绿底 + 浅绿字),有轻微填充感 |
| **wip 进行中** | 橙色背景(深橙底 + 浅橙字),有"正在工作"提示 |
| **todo 待做** | 灰色 + 虚线边框,**绝不能让 todo 看起来比 lit 更突出** |

**Why**:三态颜色语义全 dashboard 一致;todo 视觉权重必须最低,否则"未做"会比"已做"更显眼,挫败感强。

---

## § 8 MVP 分期

### § 8.1 4 期 ship,共 9-13 天 wall time

| 期 | 内容 | 量级 | ship 标准 |
|---|---|---|---|
| **M1** | Source + Derive + State + 主视图(8 维 cards 只读 + Hero milestone) | 3-4 天 | 浏览器看到当前进度,无编辑无 toggle 无侧栏 |
| **M2** | 决策侧栏 + 矩阵 toggle + 时间线 toggle | 2-3 天 | 三视图切换流畅,决策日志按 layer/state filter |
| **M3** | 编辑模式(focus / blockers / capability override) | 2-3 天 | 关闭浏览器再打开,手填内容仍在 |
| **M4** | 公开页 `/dashboard` + 脱敏投影 + portfolio 叙事 | 2-3 天 | AllowlistDriftTest 100% 覆盖,无敏感字段泄漏 |

**M1 是实际可用 MVP**(虽然只读,但解决 ACD 痛点);M3 后完整覆盖 ACDE;M4 是 portfolio 物料,可推后到任何时候。

### § 8.2 量级评估假设

- 每天 4-5h Claude Code 投入(memory `feedback_estimate_in_claude_code_walltime`)
- 周末加倍
- 假设无 cassette 重录 / dependency 引入
- M2 矩阵 + 时间线 是新组件,工程量按 skill 实施估;skill 调用本身不增加 wall time(已在 hook 内)

### § 8.3 与其他 epic 的依赖

- **强依赖**:v0.9.x frontend rebrand ship(本 spec 嵌入 frontend,需要稳定的 layout / auth / routing)
- **建议依赖**:v0.9.0 投资尽调 use case 内化 ship(decision_extractor 能从更多 spec 中收集数据)
- **无依赖**:Memory layer / Auto-repair / 其他 v1.0+ epic(本 spec 工具属性,不阻塞主线)

**推荐启动时机**:v0.9.x ship 后立即;或与 v1.0 横切层 epic 并行(本 spec 工程量小且独立)。

---

## § 9 测试策略

### § 9.1 派生层(Derive)

**Golden 模式**(memory `project_eval_pipeline_contract` 的延续):

```
backend/tests/dashboard/derive/
  ├── fixtures/
  │   ├── sample_specs/         # 冻结的 spec markdown 子集
  │   ├── sample_plans/
  │   ├── sample_memory/
  │   └── sample_git_log.txt
  └── golden/
      ├── expected_dimensions.json
      ├── expected_milestones.json
      ├── expected_capabilities.json
      └── expected_decisions.json
```

每次派生层改动必须:
1. 跑 `pytest backend/tests/dashboard/derive` → 对比 golden,任何 diff fail
2. 如确定要改 golden,显式 `pytest --update-golden` 重生成 + commit + 在 PR 描述写"派生 golden 更新原因"

### § 9.2 状态层(State)

标准 sqlite CRUD 测,覆盖:
- handfill_focus 单行更新语义
- handfill_blockers 增删 / resolved 时间戳
- handfill_capability_override 设置 / 清除
- handfill_decision_tags toggle

### § 9.3 API 层

每个 endpoint:
- 200 happy path
- 401 未鉴权(`/admin/*`)
- 422 请求体非法(POST 端点)
- AllowlistDriftTest(§ 6.2,关键)

### § 9.4 投影脱敏(关键)

**`test_public_snapshot_allowlist_drift.py`**:

```python
def test_admin_fields_explicitly_classified():
    """新增 AdminSnapshot 字段必须在 PublicSnapshot 或显式 ADMIN_ONLY 名单"""
    admin_fields = set(AdminSnapshot.__fields__.keys())
    public_fields = set(PublicSnapshot.__fields__.keys())
    classified = public_fields | KNOWN_ADMIN_ONLY_FIELDS
    drift = admin_fields - classified
    assert not drift, (
        f"未分类字段 {drift} — 必须显式加入 PublicSnapshot 或 KNOWN_ADMIN_ONLY_FIELDS"
    )
```

**这是 portfolio 翻车防御** — 一个忘记脱敏的字段 = 信任损伤。CI 必须 block 这种漂。

### § 9.5 E2E

跑当前项目 spec/plan/memory 真实数据做一次完整 derive → 验证:
- 不报错 / 不空 / 覆盖所有 milestone
- 35/60 capability 计数与 § 3.4 anchor 一致(回归保险)
- App Shell 6 项都能识别到至少 1 个 commit

### § 9.6 UI 层(skill 决定)

实施阶段 `frontend-design` / `taste-skill` 决定 component test 策略;spec 固化:
- 至少有 visual regression test(snapshot)
- 关键交互(toggle / 编辑模式)有 e2e

---

## § 10 业界对齐说明

简历直接讲"我做了完整 8 维 LLM Harness"时,业界共识对照(防被反驳):

| 我们的 | 业界主流命名 | 标志性产品 / 文献 |
|---|---|---|
| 01 Prompt & Context | Prompt Engineering / Context Engineering | Anthropic Skills bundle / OpenAI Cookbook / DAIR.AI guide |
| 02 Tools & Function Calling | Tool Use / Function Calling / Actions | **MCP 协议(Model Context Protocol)** / OpenAI Functions / Anthropic Tools |
| 03 Orchestration / Multi-Agent | Agent Orchestration / Workflow | **LangGraph** / CrewAI / AutoGen / Anthropic Subagents |
| 04 Memory | Memory(短期 / 长期 / 语义) | **Letta(原 MemGPT)** / mem0 / LangChain Memory |
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

## § 11 Open Questions(留给 implementation 阶段)

以下问题不影响 spec 完整性,但 implementation 阶段需要 brainstorm 决定:

1. **派生层缓存策略**:每次刷新全跑(慢但简单)vs 增量(快但复杂)?推荐 M1 全跑,M2 看实测时间决定是否做增量。
2. **Decision ID 稳定哈希算法**:用于 `handfill_decision_tags.decision_id`。要求:同一决策跨刷新 ID 不变;决策内容修改后 ID 应变化(以触发 re-approve)。候选:`sha256(version + layer + title)[:12]`。
3. **Capability yaml 版本化**:capability 清单本身的演化怎么追踪?yaml diff 进 git history 还是单独有"capability schema 版本"?推荐 git 即可。
4. **公开页 SEO 与隐私**:`/dashboard` 是否允许 search engine 索引?推荐**不索引**(meta robots noindex),作者主动分享链接给面试官,被搜到反而不好。
5. **decisions filter UI**:决策日志侧栏的 layer / state filter 是 chip 多选还是 dropdown?skill 决定。
6. **公开页项目叙事文案**:hero 那段"通用金融 agent 平台 + 首个落地 use case"要不要支持作者自定义?推荐 v1 写死在配置文件,v2 看需求。
7. **Capability override 的 drift 检测**:作者手动 force-lit 一项,但代码里 grep 早已能命中——是不是该提示"override 已多余,可删"?推荐 M3 加这个 hint。

---

## § 12 与 v0.9+ Roadmap 的关系

本 spec 工具属性,不属于 v0.9+ roadmap § 2 任何阶段;但作为**支撑工具**可在阶段 2-3 之间穿插实施,工程量小(9-13 天)且独立。

ship 后:
- 作者日常打开 `/admin/dashboard` 跟进开发(对抗"把控感缺失")
- 简历刷新时引用 `/dashboard` 公开页作为 portfolio 物料
- 每 milestone ship 后,作者在编辑模式 approve 新决策的公开可见性

**memory 落地**:本 spec ship 后,memory 新增:
- `project_dashboard_landed.md` — ship 状态 + capability 总数 + 60 项清单
- `feedback_capability_yaml_governance.md` — 维护经验(如有)
- `reference_dashboard_url.md` — 内部 / 公开访问入口
