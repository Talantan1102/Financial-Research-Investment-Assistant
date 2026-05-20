# Harness Board 维度从「自定义 8 维」迁移到「ETCLOVG 7 维」— 设计文档

**作者**：Talantan1102
**起草**：2026-05-20
**状态**：Spec（待 plan 拆分）
**类型**：Refactor / Re-taxonomy + 数据迁移 + UI 重做（一次性硬切）
**参考论文**：Li et al., *Agent Harness Engineering: A Survey*, 2026（PDF：`/Users/talantan/Downloads/50714_Agent_Harness_Engineerin.pdf`）

---

## § 0 元信息与范围

### 0.1 触发动机

2026-05-20 用户读论文后提议：把看板的维度分类从自定义 8 维 + App Shell catch-all（v0.7~v0.8.5 累积自创术语）改为论文权威 ETCLOVG 7 维。

| 当前 8 维（自创） | 论文 ETCLOVG 7 维 |
|---|---|
| Prompt & Context / Tools & Function Calling / Orchestration / Memory / RAG & Knowledge / Guardrails & Auto-Repair / Eval & Observability / Cost & Routing | Execution / Tooling / Context / Lifecycle / Observability / Verification / Governance |
| **+ App Shell catch-all**：frontend / backend / auth / database / connectors / infra | — |

**这不是简单 rename**，是 3 维合并（prompt+memory+RAG → C） + 1 维拆分（eval+obs → V+O） + 1 维迁移（cost → O 子层） + 1 维升格（infra → E 一等公民） + 1 维归并（auth → G）。

### 0.2 为什么不能继续用自定义 8 维（问题陈述）

| 维度 | 当前问题 | 论文权威立场 |
|---|---|---|
| **Eval & Observability 合并** | 监控基础设施（Langfuse / OTel / cost tracking）与评测体系（Judge / Golden / Regression）放一层，掩盖两者工程栈完全不同 | §2.3 明确："promote Observability to an independent layer rather than treating it as a side effect of lifecycle hooks ... distinct engineering practices warrant independent treatment" |
| **Memory + RAG 分立** | Memory 与 RAG 都是 "model 在每一步能看见什么" 的子问题（短期窗口 / 中期 session / 长期记忆 / RAG 同属一个连续光谱），分立后跨子层 design discussion 重复 | §5（C 层）：短期 / 中期 / 长期 / long-horizon 四子层统一处理；§5.5 长期记忆显式覆盖向量库 + RAG |
| **Cost & Routing 单立一维** | cost tracking 是 observability §7.3 的子层；router 决策是 §11.1 cost-quality-speed trilemma 的跨层议题，单独立维容易在改 router 时漏掉对 obs 子系统的影响 | §7.3 "Cost Tracking and Optimization" 明确在 O 层 |
| **Guardrails 独立维 + Auth 混进 App Shell** | guardrails / pii / hallucination check / pydantic schema 都是 G 层"component hardening" + "declarative constitutions" 的子项；auth 是 §9.1 permission models 核心，被降级到 App Shell catch-all 失去权重 | §9 把 permission/identity + lifecycle hook + hardening + constitutions + audit 统一为 G 一等层 |
| **Execution Environment 完全缺位** | 当前看板**没有** sandbox / 容器 / 部署模式这一维，只在 App Shell 的 infra 子项里有 docker / CI 的"路径归类"，无 capability 自检 | §3 把 E 列为第一层，论文核心论点之一："agent sandboxing 是 security + reproducibility + liveness 三合一，elevates from operational detail to first-class concern" |
| **简历叙事 friction** | 面试官读"自定义 8 维 LLM Harness"需要先理解你的术语；ETCLOVG 是 2026 学界与 OpenAI/Anthropic/LangChain 工程实践对齐的命名 | §1.2 The Practitioner–Research Gap：论文整篇为"补齐 vocabulary"而写 |

### 0.3 范围边界

**做**（信息结构层）：
- `dashboard/config/dimensions.yaml` 全文重写（8 → 7 维 + `catch_all:` 顶层独立 key）
- `dashboard/config/capabilities.yaml` 62 capability 全部按新维度重归属 + 部分新增 E/G 子项
- `dashboard/derive/types.py` `DimensionId` Literal 改 7 项
- `dashboard/derive/path_router.py` glob 规则 + 注释对齐
- 数据迁移：`deep_cards_seed.jsonl` 35 张（cap_id rename） + `external_agent_survey.jsonl` 53 条（dimension 字段改值）
- 11 个测试 golden 期望值刷新
- `dashboard/server.py` 一处 sentinel 字符串

**做**（视觉风格层 — 同步从 Quiet Workshop 切换到 iOS Calm Minimal，见 § 4A）：
- 起草 `dashboard/static/mockup-v3.html` 锁定视觉（self-contained HTML，4 核心场景）
- `dashboard/static/style.css` 整套重写（暖黑作坊 → 浅色 iOS 系统感）
- 13 个 Jinja 模板视觉调整（`overview.html` / `story.html` / `survey.html` / `flashcards_stats.html` / `_d_view.html` / `_app_shell.html` / `_hero.html` / 各 partial / `mockup-v2.html` 保留作 V2 历史 reference 不删）
- Fingerprint SVG 8 spoke → 7 spoke + 视觉弱化（单色 indigo / 50% opacity / footer 角落小尺寸）
- 字体栈替换（Newsreader serif / Source Han Serif → -apple-system + SF Pro 栈）
- MEMORY.md 同步：新增 `project_etclovg_migration_2026-05-20.md` 条目 + MEMORY.md 索引加一行；旧条目（v0.7 / v0.8.5 / harness-board-v2-polish-done 等）不动

**不做（真 YAGNI）**：
- alias / 兼容层 — 一次性硬切（v0 internal tool，无外部消费者）
- 各 capability 的 derive_rule 重写（仅在归属换层后顺手修复明显失效的 path_glob）
- 持久化 schema 迁移（已确认 sqlite 无 dimension 列）
- LangFuse / OTel 实际接入（V/O 层的 observability instrumentation 是 v1 单独 spec）
- 深色模式（iOS Calm Minimal 只做 Light Mode，决议 § 10.Q1）
- mockup-v2.html 删除（保留为 V2 历史 reference）

### 0.4 关键 memory 引用

- `feedback_no_portfolio_simplification` — 个人项目也要工业级三维评估
- `feedback_design_doc_format` — 每个非平凡决策必须四件套（问题/alts/tradeoff/量化）
- `project_v0.8.5_architecture_landed` — 当前架构 anchor（17-component Skills / Critic 7th / constrained router 等需重归 G）
- `project_harness_board_v2_polish_done` — V2 polish 视觉系统是本次重做的视觉底座（fingerprint / 配色 / 字体不动）
- `feedback_unguarded_imports_after_delete` / `feedback_legacy_module_init_grep` — 删除/重命名 capability id 时必须 grep 引用面再动

---

## § 1 七维定义（基于论文 §2.3 + §3-§9）

### 1.1 ETCLOVG 速查

| 字母 | 全称（中/英） | 论文锚点 | 我们项目的覆盖锚点 |
|---|---|---|---|
| **E** | 执行环境与沙箱 / Execution Environment & Sandbox | §3 | docker / docker-compose / CI workflow / venv 隔离 / tushare cache sqlite / Milvus 独立容器 |
| **T** | 工具接口与协议 / Tool Interface & Protocol | §4 | `backend/app/tools/**` + `tool_registry` + MCP bridge + tushare/bocha/milvus client 适配 |
| **C** | 上下文与记忆 / Context & Memory Management | §5 | LLMService tier/schema + Skills bundle + checkpointer + RAG/Milvus + 长期 memory |
| **L** | 生命周期与编排 / Lifecycle & Orchestration | §6 | LangGraph 骨架 + 5-agent + Send/subgraph + SSE + SqliteSaver state + chat session 持久化 |
| **O** | 可观测与运营 / Observability & Operations | §7 | TraceService + cost tracking (pricing/cost_budget/quota) + TierRouter + monitoring/B-3 引擎 + harness board 本身 |
| **V** | 验证与评测 / Verification & Evaluation | §8 | EvalRunner + Judge + Golden cases (15+) + L2 cassette + 289+ pytest + differential golden |
| **G** | 治理与安全 / Governance & Security | §9 | Auth + Constrained router + Pydantic schema + Critic per-step + LangGraph retry edge + 未来 PII/audit |

### 1.2 论文两个设计原则（本 spec 必须遵从）

引自 §2.3：

1. **Observability 是一等层**（不是 lifecycle hook 的副作用）：production 里 obs 有独立的工具生态（Langfuse / Arize Phoenix / OpenLLMetry）和工程实践（OTel instrumentation / cost attribution / anomaly detection）。
2. **Governance 是一等层**：三子层（model-level guardrails、system-level gateways/proxies、organizational-level audit/HITL）。

引申到本项目：
- 不再把 "TraceService" 和 "EvalRunner" 当同一维（V1 决策错误）
- 不再把 auth 当 "App Shell 基础设施"（V1 错位）
- 不再把 cost_routing 当独立维（合并到 O）

### 1.3 状态管理放在哪？

论文 §2.3 末段："State management belongs naturally inside Lifecycle and Orchestration (L), alongside the execution flow that reads and writes it." — 因此 `SqliteSaver` / `checkpointer` 主归 **L**，C 层只关心 "model 一步看到什么"（窗口 / 检索 / 召回结果）。

> ⚠ 当前 capabilities.yaml 把 `session_checkpoint` 放在 04 Memory，把 `sqlite_saver` 放在 03 Orchestration，**重复且错位**。新版统一：checkpointer 仅在 L 出现一次。

---

## § 2 当前 8 维 → 新 7 维 完整映射表

### 2.1 维度级映射

| 现状 dim_id | 现状 cap 数 | → 新 ETCLOVG | 备注 |
|---|---|---|---|
| `prompt_context` | 8 | → **C** | 整体并入 |
| `tools_function` | 8 | → **T** | 直接对齐，id rename `tools_function` → `tool` |
| `orchestration` | 9 | → **L** | 直接对齐，id rename `orchestration` → `lifecycle` |
| `memory` | 6 | → **C**（其中 `session_checkpoint` 迁 L） | 合并入 C |
| `rag_knowledge` | 8 | → **C** | 合并入 C（论文 §5.5 长期记忆子层） |
| `guardrails` | 7 | → **G** | 整体迁入 G |
| `eval_observability` | 9 | → **拆为 O + V** | 见 2.3 细分 |
| `cost_routing` | 7 | → **O**（子层） | 论文 §7.3 cost tracking 在 O |
| App Shell.frontend | — | → 仍 catch-all **shell** | 留 catch-all 不归一等维 |
| App Shell.backend | — | → 部分 **L**（router/app_main），部分 catch-all | 拆 |
| App Shell.auth | — | → **G** | auth = §9.1 permission/identity 一等公民 |
| App Shell.database | — | → **E** | sqlite/pg 是执行环境的持久化层 |
| App Shell.connectors | — | → **T** | tushare/bocha/milvus client 是 tool integration |
| App Shell.infra | — | → **E** | docker/CI/scripts → 升格 E 一等公民 |

### 2.2 capability id 级 rename（影响 cap_id 持久化字段，必须批量改）

新 capability id 命名约定：`<new_dim>.<cap_local_id>`，cap_local_id 不变（除非语义改了）。映射示例（完整表见 § 4）：

| 旧 cap_id | 新 cap_id |
|---|---|
| `prompt_context.constrained_schema` | `context.constrained_schema` |
| `prompt_context.skills_bundle` | `context.skills_bundle` |
| `memory.session_checkpoint` | `lifecycle.session_checkpoint`（迁 L 层） |
| `rag_knowledge.milvus_3_collection` | `context.milvus_3_collection` |
| `guardrails.constrained_router` | `governance.constrained_router` |
| `eval_observability.trace_service` | `observability.trace_service` |
| `eval_observability.eval_runner` | `verification.eval_runner` |
| `eval_observability.dashboard` | `observability.harness_board` |
| `cost_routing.tier_router` | `observability.tier_router` |

> ⚠ cap_id 是 `deep_cards_seed.jsonl` 35 张卡片的主键，rewrite 时必须 1:1 map，禁止漏。

### 2.3 `eval_observability` 9 项的 O/V 拆分（论文 §7 vs §8）

| 旧 cap | 新归属 | 论文锚点 |
|---|---|---|
| `eval_runner` | **V** | §8.4 Controlled Execution and Trace Capture |
| `trace_service` | **O** | §7.1 Tracing and Monitoring Platforms |
| `llm_judge` | **V** | §8.5 Multi-level Judgement and Failure Attribution |
| `golden_cases` | **V** | §8.2 Task and Benchmark Grounding |
| `cassette_l2` | **V** | §8.4 Controlled Execution（cassette 是 reproducibility tool）|
| `test_suite` | **V** | §8 整体 |
| `ab_testing` | **V**（regression compare）| §8.6 Continuous Regression |
| `latency_p95` | **O** | §7.4 Reliability Engineering |
| `dashboard` (harness board 本身) | **O** | §7.5 Unified Observability |

### 2.4 `cost_routing` 7 项全归 O

论文 §7.3 明确 "Cost Tracking and Optimization" 在 O 层。`tier_router` 归 O 看似有歧义（router 也参与 lifecycle），但论文 §11.1 cost-quality-speed trilemma 是 obs-driven 决策，所以 router 决策的**观测信号**（pricing / cost_budget）是 O 范畴，router 的**执行边**仍在 L（add_edge）— 这里我们用 capability 表征执行边的"信号源"，归 O 不歧义。

### 2.5 新增 E 层 capability（首版 7 项 — 决议含 Celery/Redis）

E 层从无到有，论文 §3.2 七子类挑选与项目当前架构相关者：

| 新 cap | derive_rule | 论文锚点 |
|---|---|---|
| `execution.docker_compose` | `file_exists: docker-compose.yml` | §3.4 Deployment Modes |
| `execution.container_isolation` | `file_exists: docker/` | §3.2.1 General-Purpose Managed Sandboxes |
| `execution.ci_workflow` | `file_exists: .github/workflows/` | §3.4 Deployment Modes |
| `execution.venv_isolation` | `file_exists: pyproject.toml`（uv-managed venv） | §3.2.6 OS-level（弱版） |
| `execution.persistence_layer` | `file_exists: backend/data/`（sqlite 集合） | §3.1 Scope（reproducibility + state） |
| `execution.tushare_cache_isolation` | `file_exists: backend/data/tushare_cache.sqlite` | §3.1 reproducibility |
| `execution.celery_redis` | `code_grep: celery\|Celery` in `backend/app/**/celery*` 或 `file_exists: backend/app/tasks/`（v0.8.6 chat-persistence Plan 2 异步队列） | §3.1 **liveness** — 异步执行让 agent 行为可恢复 |

预期 lit：6-7（基本都已存在），把当前缺位的一维一次性补满。

> ⚠ `celery_redis` 的 derive_rule 实施 plan 阶段必须先 grep 验证实际 celery 模块路径（参 `feedback_legacy_module_init_grep`），避免 plan 写死路径但实际不匹配。

---

## § 3 关键决策（非平凡，每个走四件套）

### D1：App Shell catch-all 处理 — 完全打散还是保留？

**问题**：当前 App Shell 6 项（frontend/backend/auth/database/connectors/infra）是 "代码路径归类用，不算 capability 维度" 的特殊存在，承担 path_router fallback 与 D-view（代码地图）的代码归类职责。完全打散后，frontend/backend 这种泛路径归到 7 维哪一个都不准。

**Alternatives**：

| 方案 | 描述 | 取舍 |
|---|---|---|
| A. 完全打散 | 把 6 项全部归到 7 维，强行归类 | frontend 归 C？归 L？都歧义；强归会污染 capability 自检 |
| B. **保留 catch-all "shell"**（推荐） | 7 维主泳道 + 1 个 `shell` catch-all，仅作 path_router fallback 与 D-view 代码地图用，不参与 fingerprint / overview / flashcards 主视图 | 7 维专注 capability，catch-all 专注代码地图，两套语义分离 |
| C. 保留 6 项但归到 7 维子层 | App Shell 下挂在某个一等维下 | 把 auth 强挂 G、把 infra 强挂 E 后，剩下的 frontend/backend 仍无去处，方案不彻底 |

**取舍**：B。理由：
1. 论文 §2.4 Scope 明确 harness 是 "engineered wrapper around model"，frontend / 普通 backend router 本来就不是 harness 的研究对象；强归会扭曲 7 维语义
2. catch-all 改名 `shell`（不再叫 App Shell）避免和 ETCLOVG 维度命名混淆
3. D-view 代码地图是用户实际用得到的功能（看代码改动落在哪里），不能为对齐论文砍掉

**量化评估**：path_router 命中率统计——迁移前后 backend/ 下 .py 文件归到 7 维主泳道的比例（目标 ≥ 80%，剩余 ≤ 20% 落 `shell`）。

### D2：Memory + RAG + Prompt/Context 全进 C 是否过粗？

**问题**：合并后 C 层会有 8+6+8=22 capability，是 7 维里最大的一维，视觉上 fingerprint spoke 不平衡。

**Alternatives**：

| 方案 | 描述 | 取舍 |
|---|---|---|
| A. 全部并入 C 平铺 | 22 项平铺在 C 层 | 维度内部失衡，但符合论文严格定义 |
| B. **C 层引入子分组**（推荐） | C 层下分 3 子组：`short_term`（prompt/skills/tier）/ `mid_term`（session/checkpoint 部分）/ `long_term`（memory/RAG/embedding），渲染时折叠展开 | 论文 §5.3-§5.5 本身就是这三子层，自然映射 |
| C. 把 RAG 单独提出来当 8th 维 | 违反论文 ETCLOVG 7 维定义 | 违反论文整体框架，否决 |

**取舍**：B。理由：
1. 论文 §5.3 short-term / §5.4 mid-term / §5.5 long-term 本身就有三层结构，子分组完全对齐
2. capabilities.yaml schema 加一个 `group:` 字段即可，不改维度层级
3. fingerprint SVG 仍是 7 spoke，每 spoke 分子段渲染（视觉解决方案）

**量化评估**：C 层 fingerprint spoke 的 dot 数 ≤ 8（与其他 spoke 视觉权重相当），子分组渲染在 overview 时不破坏 7 簇 layout。

### D3：cost_routing 全归 O，还是 router 留 L、cost tracking 进 O？

**问题**：`tier_router` 既是 obs 信号源（pricing / cost_budget），又是 L 的执行决策（add_conditional_edges 选哪个 agent）。

**Alternatives**：

| 方案 | 描述 | 取舍 |
|---|---|---|
| A. 全归 O | 论文 §7.3 字面 | tier_router 的 add_edge 行为在 L 看不到 |
| B. 全归 L | router 是 control flow | pricing / cost_budget 与 L 无关 |
| C. **拆开**（推荐） | `tier_router` / `pricing` / `cost_budget` / `cost_alert` / `model_caching` / `fallback_router` 归 O；`max_tokens_calibration` 归 C（prompt 配置）；router 的 **add_edge 实现** 归 L 但不作为独立 capability（已经隐含在 `lifecycle.langgraph_skeleton`）| 信号源与执行流分层，正好对齐论文 §11.1 trilemma 是跨层的论点 |

**取舍**：C。

**量化评估**：迁移后 O 层 capability 数 = trace_service + latency_p95 + harness_board + 6 cost 相关 = 9 项，与 V 层 7 项相当，平衡。

### D4：Guardrails 7 项全归 G，还是部分进 V（adversarial test）/ 部分进 L（retry edge）？

**问题**：`langgraph_retry`（重试边）本质是 L 的控制流；`adversarial_test`（对抗测试）本质是 V 的评测手段；其余 5 项（constrained_router / pydantic_schema / per_step_critic / pii_redaction / hallucination_check）是 G 的核心。

**Alternatives**：

| 方案 | 描述 | 取舍 |
|---|---|---|
| A. 全归 G | 简单 | 误归 retry edge 和 adversarial test |
| B. **三拆**（推荐） | G: 5 项 / L: 1 项 (retry edge) / V: 1 项 (adversarial test) | 严格对齐论文 |
| C. 留在 G 不拆 | 维持原样仅改名 | 违反论文 §9 G 层 = constraint + audit 语义 |

**取舍**：B。

**量化评估**：拆分后 G 层 5 项 + L 层多 1 项 + V 层多 1 项，三层数量更均衡（4/9/6/8/9/7/5 → 6/8/22/9/9/7/5，C 仍最大但其余更平衡）。

### D5：E 层 capability 首版怎么选？— 5 项 vs 全套 §3.2 七子类

**问题**：E 层从无到有，论文 §3.2 列了 7 类 sandbox 体系，全套自检过度（agent computer use / browser eval 我们没做）。

**Alternatives**：

| 方案 | 描述 | 取舍 |
|---|---|---|
| A. 全套 §3.2 七子类自检 | 列 7 子类 capability + 标 5 个 todo | 看板上 5/7 红，叙事变成"做不到"而非"已做" |
| B. **首版 5-6 项实做覆盖**（推荐） | docker_compose / container_isolation / ci_workflow / venv_isolation / persistence_layer / tushare_cache_isolation 全可自动 lit | 真实反映项目执行环境状态，避免"todo 列表炫耀" |
| C. 只 1-2 项 | 仅 docker_compose + ci | E 层过单薄，仍像 placeholder |

**取舍**：B。理由：portfolio 应展示真做了什么，不展示"todo 路线图"。

**量化评估**：E 层首版 lit 数 5/6（≥83%），与 T/L 等强项相当。

### D6：fingerprint SVG 8 spoke → 7 spoke 视觉重做

**问题**：当前 fingerprint 是 8 spoke 放射图（memory 维特殊高光 amber），改 7 spoke 后需重新设计黄金角度 + 双强调高光维。

**Alternatives**：

| 方案 | 描述 |
|---|---|
| A. **7 spoke 等分 51.4°**（推荐） + C 维 amber 高光 | 论文 C 层最大 + 是 portfolio 重头戏（context engineering 是 §2.2 三阶段第二阶段），最适合做高光维；其余 6 spoke teal |
| B. 7 spoke 等分 + 无高光维 | 视觉平淡，失去当前 fingerprint 的"作品签章感" |
| C. 改为 7 边形 polygon 代替 spoke | 与现有 SVG 工艺不符，重做成本高 |

**取舍**：A。

**量化评估**：fingerprint 重生成后跑视觉 diff（与 v2-polish-done.md 里的 fingerprint 8 spoke 对照），保证"作品签章感" UX 不下降。

### D7：数据迁移 — in-place rewrite 还是双轨过渡？

**问题**：35 张 deep card seed + 53 条 survey 全要改 cap_id / dimension 字段；jsonl 是 git 跟踪的真源（不是 DB），改完直接 commit 即可。

**Alternatives**：

| 方案 | 描述 | 取舍 |
|---|---|---|
| A. **in-place rewrite + 一次性 commit**（推荐） | 写一个 Python migration 脚本，跑一次，diff 进 git | v0 internal tool 无消费者，一次性切干净 |
| B. 双 jsonl（old + new）alias | 留 old.jsonl 备份 | YAGNI |
| C. 手动改 88 行 | 易错 | 88 条手改风险高 |

**取舍**：A。脚本放 `dashboard/scripts/migrate_to_etclovg.py`，跑完即删（不长期存在）。

**量化评估**：脚本输入 88 行 jsonl，输出 88 行，行数 1:1，diff 仅 `cap_id` / `dimension` / `linked_capabilities` 字段变更。

### D8：MEMORY.md 文档维度叙述同步

**问题**：MEMORY.md 多处写 "8 维 LLM Harness"（v0.8.5 / harness-board-v2-polish-done / project_v0.7_architecture_landed 等条目），需同步刷成 ETCLOVG 7 维。

**Alternatives**：

| 方案 | 描述 | 取舍 |
|---|---|---|
| A. 全部硬替 "8 维" → "7 维 ETCLOVG" | 简单 | 历史 context 失真（v0.7 当时确实是 8 维） |
| B. **保持历史 memory 原文，新增 etclovg_migration 条目记录切换**（推荐） | 加 `project_etclovg_migration_2026-05-20.md` + 在 MEMORY.md 索引加一行 | 历史不失真，新事实有 anchor |
| C. 不改 MEMORY.md | 后续读 memory 会混淆 | 否决 |

**取舍**：B。

---

## § 4 完整 capability 重归属表（62 → ~64）

> **Total 变化**：62 旧 → 删除 1（重复的 `memory.session_checkpoint` 与 `orchestration.sqlite_saver` 合并）+ 新增 6 E 层 = 67 项。

### 4.1 C 层（Context）— 子分组结构（22 项）

**short_term（5 项）**：
- `context.multi_tier_signature`（← prompt_context）
- `context.constrained_schema`（← prompt_context）
- `context.skills_bundle`（← prompt_context）
- `context.per_task_registry`（← prompt_context）
- `context.max_tokens_calibration`（← cost_routing；prompt 配置语义）

**short_term manual（3 项）**：
- `context.prompt_versioning`（← prompt_context.manual）
- `context.few_shot_library`（← prompt_context.manual）
- `context.prompt_caching`（← prompt_context.manual）
- `context.ctx_compression`（← prompt_context.manual）

**mid_term（0 项 lit + manual）**：
（无现有；session_checkpoint 移到 L 层；可留空或加 manual 占位 `context.session_state` todo）

**long_term — memory（5 项 manual）**：
- `context.long_term_memory`（← memory）
- `context.semantic_memory`（← memory）
- `context.cross_user_cache`（← memory）
- `context.episodic_memory`（← memory）
- `context.memory_compression`（← memory）

**long_term — RAG（8 项）**：
- `context.milvus_3_collection`（← rag_knowledge）
- `context.embedding_cache`（← rag_knowledge）
- `context.corpus_ingest`（← rag_knowledge）
- `context.bocha_web`（← rag_knowledge）
- `context.kb_reliability`（← rag_knowledge）
- `context.reranker`（← rag_knowledge.manual）
- `context.hybrid_search`（← rag_knowledge.manual）
- `context.query_decomposition`（← rag_knowledge.manual）

### 4.2 T 层（Tool）— 8 项

全量从 `tools_function` 改前缀 → `tool.<cap>`，capability 内容不变。
- `tool.tool_registry`
- `tool.schema_validated_io`
- `tool.di_mock_real`
- `tool.reliability_layer`
- `tool.financial_tools`
- `tool.mcp_bridge`
- `tool.tool_versioning` (manual)
- `tool.parallel_tool_calls` (manual)

### 4.3 L 层（Lifecycle）— 9 项

`orchestration` 8 项原班 + 从 memory 迁来 1 项：
- `lifecycle.langgraph_skeleton`（← orchestration）
- `lifecycle.typed_state`
- `lifecycle.send_subgraph`
- `lifecycle.critic_7_stage`
- `lifecycle.sse_streaming`
- `lifecycle.session_checkpoint`（合并旧 `memory.session_checkpoint` + `orchestration.sqlite_saver` — 论文 §2.3 明确 state 在 L）
- `lifecycle.langgraph_retry`（← guardrails；retry edge 本质是 L 控制流）
- `lifecycle.plan_and_execute` (manual)
- `lifecycle.human_in_the_loop` (manual)
- `lifecycle.agent_handoff` (manual)

### 4.4 O 层（Observability）— 9 项

从 `eval_observability` 拆 + `cost_routing` 整体迁来：
- `observability.trace_service`（← eval_observability）
- `observability.latency_p95` (manual)
- `observability.harness_board`（← eval_observability.dashboard）
- `observability.tier_router`（← cost_routing）
- `observability.pricing_table`（← cost_routing）
- `observability.cost_budget`（← cost_routing）
- `observability.model_caching` (manual)
- `observability.fallback_router` (manual)
- `observability.cost_alert` (manual)

### 4.5 V 层（Verification）— 6 项

从 `eval_observability` 拆 + `guardrails.adversarial_test`：
- `verification.eval_runner`
- `verification.llm_judge`
- `verification.golden_cases`
- `verification.cassette_l2`
- `verification.test_suite`
- `verification.ab_testing` (manual)
- `verification.adversarial_test`（← guardrails；manual）

### 4.6 G 层（Governance）— 5 项 + 新 auth（共 6 项）

从 `guardrails` 5 项 + 从 App Shell.auth 升格：
- `governance.constrained_router`（← guardrails）
- `governance.pydantic_schema`
- `governance.per_step_critic`
- `governance.pii_redaction` (manual)
- `governance.hallucination_check` (manual)
- `governance.auth`（← App Shell.auth；新归一等公民）derive_rule: `file_exists: backend/app/router/auth_router.py`

### 4.7 E 层（Execution）— 7 项（新增）

见 § 2.5。

### 4.8 catch-all（yaml 顶层 `catch_all:` 与 `dimensions:` 平级独立 key）

> **结构约束（D3 决议）**：yaml 顶层有 `dimensions:` 和 `catch_all:` 两个 key，前者是 ETCLOVG 7 维（参与 fingerprint / overview / flashcards 主视图），后者是 catch-all（仅 path_router fallback + D-view 代码地图）。

5 个 catch-all 条目，命名沿用 `shell.` 前缀以保持直觉但**类型上独立**：
- `shell.frontend`（frontend/src/**）
- `shell.backend_router`（backend/app/router/** + app_main.py + core/**）
- `shell.database`（backend/data/*.sqlite — D-view 用，与 `execution.persistence_layer` 不重；E 是 capability 自检，shell 是路径归类）
- `shell.connectors`（fallback：未被 T 层主泳道 path glob 命中的 connector 文件）
- `shell.infra`（fallback：未被 E 层主泳道命中的 docker/CI/scripts 边角文件）

**path_router 优先级**：主泳道 7 维 path glob 命中时优先；不命中才落 catch-all；都不命中返 `unknown`。

---

## § 4A 视觉语言：iOS Calm Minimal（替换 V2 的 Quiet Workshop）

### 4A.0 整体定位反转

| 维度 | V2 Quiet Workshop（2026-05-14 ship） | V3 iOS Calm Minimal（本次切换） |
|---|---|---|
| 整体明度 | 暖黑作坊（`#0c0908` ink 主底） | 浅白系统（`#F5F5F7` off-white 主底） |
| 视觉密度 | 信息密集 + 装饰元素（fingerprint / numeral 水印 / drop cap） | 大留白 + 极简装饰，删 numeral / drop cap |
| 字体气质 | 文学感（Newsreader serif + Source Han Serif） | 系统感（-apple-system / SF Pro 全栈 sans） |
| 分割手段 | hairline 虚线 + dashed border | 弱阴影 + 极淡 hairline + 卡片色块自然分割 |
| 强调色 | 双强调（琥珀 `#c89456` + 古铜青 `#6f9494`）饱和度高 | 单主色（iOS Indigo `#5E5CE6`）柔和饱和 |
| 模式 | Dark Only | **Light Only**（决议 § 10.Q1） |

### 4A.1 颜色 token（写入 `dashboard/static/style.css` 顶部 `:root`）

```css
:root {
  /* 中性色 — 浅色为主 */
  --bg:           #F5F5F7;  /* iOS 系统底（off-white） */
  --surface:      #FFFFFF;  /* 卡片底 */
  --surface-2:    #FBFBFD;  /* 次级卡片底 / nav rail */
  --hairline:     rgba(60, 60, 67, 0.12);  /* iOS 标准分割线 */
  --hairline-2:   rgba(60, 60, 67, 0.06);
  --text:         #1D1D1F;  /* 主文本（近黑，不纯黑）*/
  --text-sec:     #6E6E73;
  --text-tert:    #86868B;
  --text-quat:    #C7C7CC;

  /* 强调色 — iOS Indigo */
  --accent:       #5E5CE6;
  --accent-soft:  rgba(94, 92, 230, 0.08);  /* 填充 */
  --accent-glow:  rgba(94, 92, 230, 0.20);  /* hover */
  --accent-deep:  #4845C2;  /* border / pressed */

  /* 状态色 — 柔和饱和（lit/wip/todo 三态视觉区分）*/
  --lit:    #34C759;  /* iOS Green */
  --lit-soft:  rgba(52, 199, 89, 0.12);
  --wip:    #FF9F0A;  /* iOS Orange */
  --wip-soft:  rgba(255, 159, 10, 0.12);
  --todo:   #C7C7CC;  /* iOS Gray 4 */
  --todo-soft: rgba(199, 199, 204, 0.20);

  /* 圆角 */
  --radius-sm: 8px;
  --radius-md: 12px;
  --radius-lg: 16px;
  --radius-pill: 22px;

  /* 阴影 */
  --shadow-1: 0 1px 2px rgba(0,0,0,0.04), 0 0 0 0.5px rgba(0,0,0,0.05);
  --shadow-2: 0 4px 16px rgba(0,0,0,0.08), 0 0 0 0.5px rgba(0,0,0,0.05);
  --shadow-modal: 0 16px 48px rgba(0,0,0,0.16), 0 0 0 0.5px rgba(0,0,0,0.08);

  /* 毛玻璃 */
  --blur-strong: blur(20px) saturate(180%);
  --blur-soft: blur(12px) saturate(150%);
}
```

### 4A.2 字体栈

```css
:root {
  --font-system:
    -apple-system, BlinkMacSystemFont,
    "SF Pro Display", "SF Pro Text",
    "PingFang SC", "Hiragino Sans GB",
    "Microsoft YaHei", system-ui, sans-serif;
  --font-mono:
    "SF Mono", "Geist Mono", "JetBrains Mono",
    "Source Han Mono SC", ui-monospace, monospace;
}

body { font-family: var(--font-system); font-weight: 400; }
h1, h2, h3 { font-weight: 600; letter-spacing: -0.02em; }
.code, code, pre { font-family: var(--font-mono); }
```

- 删除：Newsreader 可变 opsz / Source Han Serif / Fraunces / Manrope（V2 全套 serif）
- 保留：Geist Mono（仍作 mono fallback，被 SF Mono 优先）

### 4A.3 圆角 / 阴影 / 间距规则

| 元素 | radius | shadow | padding |
|---|---|---|---|
| `.card` / `.deep-card-modal` | `--radius-md` 12px | `--shadow-1` | 16-20px |
| `.modal` | `--radius-lg` 16px | `--shadow-modal` | 24px |
| `.btn` / `.chip` | `--radius-sm` 8px | none | 8-12px |
| `.search-input` / `.nav-pill` | `--radius-pill` 22px | inset hairline | 8-16px |
| section gap | — | — | 24-32px |
| atom gap | — | — | 4-8px |

### 4A.4 装饰元素策略

| 元素 | V2 状态 | V3 策略 |
|---|---|---|
| Fingerprint SVG（作品签章） | 强存在（amber + teal 双色 8 spoke，nav rail 顶部）| **保留但弱化**（决议 § 10.Q3）：单色 accent indigo / 50% opacity / footer 右下角小尺寸 60×60px / 7 spoke 等分 51.4° / C 维高光 dot 用 indigo full opacity |
| Numeral 水印（卡片右下大数字） | 醒目 paper-2 色 24-48px | **删除**（违背 iOS 极简） |
| Drop cap（首字母大写）| 有 | **删除** |
| Hairline 虚线 | 大量使用 dashed | **极少使用** — 改用 1px solid `--hairline` |
| Section divider | 横线 + 间距 | 仅靠间距（24-32px gap） + 卡片色块自然分割 |
| Edge confidence 加权（鸟瞰图）| dashed/solid + 0.4/1.0 opacity | **保留**（功能性，鸟瞰图需要主弱路径视觉分层） |
| Nav rail backdrop | 不透明 ink-2 | **毛玻璃** — `background: rgba(255,255,255,0.72); backdrop-filter: var(--blur-strong);` |
| Lit node glow（鸟瞰图） | amber `overlay-color`/`overlay-opacity` | indigo `overlay-color` + 同机制 |

### 4A.5 关键视觉原则（写入 mockup-v3.html 顶部注释 + plan 3 task 引用）

1. **Light Mode Only** — 不实现 prefers-color-scheme dark
2. **单主色制** — 仅 indigo accent；不再双强调色（删 teal/古铜青）
3. **状态色弱饱和** — lit/wip/todo 用 `*-soft` 填充而非 saturated solid
4. **零装饰文字** — 删 numeral / drop cap / 拼贴艺术感
5. **毛玻璃 nav 与 sticky** — backdrop-filter 用在 sidebar / sticky header / modal backdrop
6. **圆角强调** — 12-16px 卡片、22px 输入框，避免锐角

### 4A.6 mockup-v3.html 范围（Plan 3 Task 1）

self-contained HTML（≤ 2000 行），含 4 个核心场景对照：
1. `/overview` 鸟瞰（7 簇 + indigo lit glow + 毛玻璃 nav rail）
2. `/story` story view（卡片网格 + 弱阴影 + 浅色背板）
3. DeepCard modal（圆角 16px + soft shadow + indigo accent + 状态 chip 用 soft 填充）
4. `/flashcards/stats` 统计页（SVG 圆环 indigo / 时间线散点 / 极简数字）

mockup-v3 用作 design source-of-truth，CSS / 模板必须对照它实施。

---

## § 5 实施 Plan 拆分预案（建议 3 个 plan）

### Plan 1：配置 + 类型 + capability 重归属（无前端改动）
**任务**：
1. 重写 `dashboard/config/dimensions.yaml`（7 维 + shell catch-all）
2. 重写 `dashboard/config/capabilities.yaml`（按 § 4 完整表）
3. 改 `dashboard/derive/types.py` Literal
4. 改 `dashboard/derive/path_router.py` 注释 + glob 顺序
5. 检查 `dashboard/derive/{snapshot_builder, graph_builder, flashcard_generator, story_builder}.py` 有无 hard-code dim id（grep + 改）
6. 改 `dashboard/server.py` 一处 `"app_shell"` sentinel → `"shell"`
7. 跑 mypy + ruff 全绿

**估算**：12-15 task / 0.5-0.75 天 wall time

### Plan 2：数据迁移（jsonl）
**任务**：
1. 写 `dashboard/scripts/migrate_to_etclovg.py` 一次性迁移脚本（输入 cap_id rename map）
2. 跑脚本，diff 进 git
3. 删除迁移脚本（不长期保留）
4. 跑 dashboard 启动 + `/refresh` 看 35 张 seed 加载成功
5. 11 个 test 改 golden 期望值（grep `prompt_context` 等旧 id，改成新 id）
6. pytest 全绿

**估算**：8-10 task / 0.5 天 wall time

### Plan 3：mockup-v3 + iOS 视觉重做 + 模板维度切换 + dogfood（范围扩大）

> **Plan 3 同时承载两件事**：(a) 维度 8→7 的模板调整 + fingerprint 重做；(b) 视觉语言整套从 Quiet Workshop 切到 iOS Calm Minimal（§ 4A）。

**任务**：
1. 起草 `dashboard/static/mockup-v3.html`（self-contained，4 核心场景：overview / story / DeepCard modal / flashcards_stats），锁定视觉
2. `dashboard/static/style.css` 整套重写（按 § 4A.1-4A.5 token + 规则；不沿用 V2 的暖黑配色 / Newsreader 字体 / numeral 装饰）
3. 13 个 Jinja 模板按 mockup-v3 视觉调整：
   - `base.html` / `_app_shell.html`（毛玻璃 nav rail）
   - `_hero.html`（删除 numeral 水印）
   - `overview.html` / `story.html` / `survey.html` / `decisions.html` / `flashcards.html` / `flashcards_stats.html`
   - `_d_view.html` / `_b_view.html` / `_d_b_toggle.html` / `_decision_card.html` / `_deep_card_modal.html` / `_story_card.html` / `_refresh_panel.html` / `_flashcard_review.html` / `_capability_chip.html`
4. Fingerprint SVG 重做：8 spoke → 7 spoke 等分 51.4° + 单色 indigo + 50% opacity + 移位 footer 右下角 60×60px + C 维 dot 用 indigo full opacity（替代 V2 的 amber 高光语义）
5. `_d_view.html` 代码地图里 catch_all 显示策略（折叠展示，5 项归一卡片）
6. cytoscape 鸟瞰：`overlay-color` 改 indigo；edge confidence 加权 保留；空状态浮条配色对齐
7. `mockup-v2.html` 保留不删（作 V2 历史 reference）
8. dogfood：5 视图 + DeepCard modal + flashcards stats + nav-rail refresh button + 7 簇视觉验证 + 字体栈生效 + 毛玻璃效果
9. MEMORY.md 新增 `project_etclovg_migration_2026-05-20.md` + 索引行（含视觉切换记录）

**估算**：18-22 task / **2-3 天 wall time**（mockup 0.5 天 + CSS 重写 1 天 + 模板调整 0.5-1 天 + dogfood 0.5 天）

**总计**：3 plan / 38-47 task / **~3.25-4.25 天 wall time**。

---

## § 6 量化评估方案

### 6.1 ship gate

| 维度 | gate | 验证手段 |
|---|---|---|
| 维度数 | 主泳道 = 7（`dimensions:` 下）+ `catch_all:` 顶层独立 key | yaml load + types Literal |
| capability 数 | 87 项（62 - 1 合并 + 7 E 新增 + 18 论文子层细分 manual） | yaml load count |
| 路径分类命中率 | backend/ 下 .py 文件归 7 维主泳道 ≥ 80%（剩余落 catch_all） | path_router 跑全 repo + 统计 |
| E 层 lit | ≥ 6/7 | capability_resolver 跑 + 自检 |
| C 层 fingerprint dot 数 | ≤ 8 dot per spoke | fingerprint 生成检查 |
| 测试 | pytest 全绿 / mypy 0 errors / ruff clean | `uv run poe ci` |
| 数据完整性 | 88 行 jsonl 迁移后仍 88 行 | wc -l before/after |
| 链接完整性 | `linked_capabilities` 所有引用都能在新 yaml 找到 | yaml load + cross-ref check 脚本 |
| 视觉 | overview / story / survey / flashcards_stats / DeepCard modal 5 视图渲染无 4xx/5xx，dim 数 = 7 | dogfood 浏览器手动 |
| SSE refresh | `/refresh` 5 step 全过（无 milvus env 时第 4 步 skip） | dogfood |
| Fingerprint | 7 spoke 等分 51.4°，单色 indigo 50% opacity，footer 右下 60×60 | 浏览器视觉对照 mockup-v3 |
| 视觉语言切换 | bg 主底色 = `#F5F5F7`，主文 = `#1D1D1F`，accent = `#5E5CE6`，圆角 ≥ 8px，无 dashed border | DevTools 取色器检查 |
| 字体栈 | computed font-family 命中 SF Pro / -apple-system，无 Newsreader/Source Han Serif | DevTools Computed 面板 |
| 毛玻璃 | nav rail + sticky header 含 `backdrop-filter: blur()`  | DevTools 检查 |
| 装饰元素 | numeral 水印 / drop cap 全删，搜索源码 0 匹配 | grep `numeral` / `drop-cap` 在 CSS 中 |

### 6.2 量化 vs v2-polish 对比

| 指标 | V2 polish ship 时（2026-05-14）| 迁移后目标 |
|---|---|---|
| 主泳道维度数 | 8 + App Shell(6) | 7 + catch_all(5) |
| capability 总数 | 62 | 87（含论文子层细分 18 项 manual） |
| 总 lit 数（snapshot） | 38（按 v0.8.5 报告） | ≥ 42（E 层贡献 6-7 新 lit；V/O 拆开后部分 lit 散到两边） |
| fingerprint spoke | 8 | 7（C 维 amber 高光） |
| 论文权威对齐 | 0%（自定义） | 100%（ETCLOVG） |

---

## § 7 风险与回滚

### 7.1 风险

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| 35 张 seed 迁移时 cap_id 漏 rename | 中 | 鸟瞰节点失联 | 迁移脚本必须先 dry-run 输出 diff 让用户审；迁移后跑 cross-ref check |
| 模板硬编码 dim id 漏改 | 中 | 模板渲染 KeyError 或 lit 数错位 | grep 全模板 + dogfood 5 视图必跑 |
| capability_resolver 对新维度的 derive_rule 失效 | 低 | 自动派生状态错 | Plan 1 完工跑 `/refresh` SSE 全 5 step 看 capability snapshot |
| Memory 子组（C 内）渲染过载 | 低 | overview C 簇视觉拥挤 | D2 子分组 + fingerprint 渲染折叠 |
| fingerprint 7 spoke 视觉权重失衡 | 中 | "签章感" 退化 | D6 选 C 维 amber 高光保持视觉锚点 |
| 测试 golden 改不全 | 中 | CI 红 | Plan 2 grep `prompt_context|tools_function|...` 全 test 文件改全 |

### 7.2 回滚

迁移整体在单 branch（`refactor/etclovg-migration`）完成，未合 main 前 `git reset --hard` 即可。merge 后回滚：
- jsonl revert（git revert）
- yaml revert
- 不存在 schema migration 需要回滚（无 DB 变更）

---

## § 8 Out of scope（不要 scope creep）

- LangFuse / OTel 实际接入（这是 v1 单独 spec — 真正把 O 层 capability lit）
- 论文 §3.2 七子类 sandbox 全套自检（E 层首版 5-6 项够，sandbox 体系本身是 v1+）
- 各 capability derive_rule 整体重写（仅顺手修明显失效）
- 多 manual capability 转 auto（manual 留 manual）
- Anthropic / OpenAI / LangChain 第三方 harness 系统的 capability 对照（这是 survey）
- 中文论文术语本地化（保留 "Observability/Verification/Governance" 英文 + 中文标签并存即可）

---

## § 9 关联 spec / plan / memory

- 论文：`/Users/talantan/Downloads/50714_Agent_Harness_Engineerin.pdf`
- 上一版视觉系统：`docs/superpowers/specs/2026-05-14-harness-board-v2-polish-design.md`
- V2 polish ship 卡：`docs/claude-context/harness-board-v2-polish-done.md`
- 后续 plan（待起草）：
  - `2026-05-20-etclovg-migration-plan1-config-types.md`
  - `2026-05-20-etclovg-migration-plan2-data-migration.md`
  - `2026-05-20-etclovg-migration-plan3-frontend-fingerprint.md`

---

## § 10 开放问题决议（2026-05-20 用户裁决）

1. **C 层子分组**：✅ 选 A — **仅 yaml 内部分组**（加 `group: short_term/mid_term/long_term` 字段），前端不分子段渲染。理由：避免"7+3" 视觉稀释 ETCLOVG 7 维核心叙事；fingerprint C spoke 用 amber 高光维处理视觉权重。
2. **E 层首版**：✅ 选 B — **补 `execution.celery_redis`**，E 层首版 **7 项**（原 6 项 + Celery/Redis）。理由：论文 §3.1 sandbox liveness 目的契合异步执行场景；Celery worker 是 v0.8.6 chat-persistence Plan 2 真做了的物理执行基础设施，portfolio 应展示。
3. **catch-all 命名**：✅ 选 D — **yaml 顶层 key 改 `catch_all:`**（与 `dimensions:` 平级独立 key），内部条目仍命名 `shell.frontend` / `shell.backend_router` / `shell.database` / `shell.connectors` / `shell.infra`。理由：结构上把"非 ETCLOVG 一等维"语义钉死，避免被误判为第 8 维。
4. **MEMORY.md 同步策略**：✅ 选 B — **新增 `project_etclovg_migration_2026-05-20.md` 条目 + MEMORY.md 索引加一行；旧条目（v0.7 / v0.8.5 / harness-board-v2-polish-done 等）不动**。理由：memory 是时间快照，旧条目记录"当时确实是 8 维"的事实，强改会让架构演进史失真。
5. **Plan 拆分**：✅ 拆 3 个独立 plan（按 § 5 预案），每 plan 完工独立可 ship 中间状态：
   - Plan 1：配置 + 类型 + capability 重归属（无前端 / 无数据迁移 — pytest 红可控，因 golden 还指向旧 id）
   - Plan 2：数据迁移（jsonl + 测试 golden 同步）
   - Plan 3：mockup-v3 + iOS 视觉重做 + 模板维度切换 + dogfood + MEMORY.md 沉淀

### 视觉语言决议（2026-05-20 用户裁决，对应 § 4A）

6. **Q1 深色模式**：✅ 选 A — **Light Mode Only**。理由：iOS 风核心是"淡雅"，做 Dark 重复 V2 Quiet Workshop 语义；CSS 量减半。
7. **Q2 主色**：✅ 选 iOS Indigo `#5E5CE6`。理由：柔和靛紫与金融研究 portfolio 调性匹配，避免 iOS Blue 过"App Store"感。
8. **Q3 Fingerprint SVG**：✅ 选 A — **保留 + 弱化**。单色 indigo / 50% opacity / footer 右下角 60×60px。保留作品签章语义，但视觉权重让渡给信息。
9. **Q4 mockup-v3.html**：✅ 选 A — **先做 mockup-v3.html 锁定视觉**。以 mockup-v2.html layout 为底，仅换视觉风格，预估 ≤ 2000 行。Plan 3 Task 1 起草。
