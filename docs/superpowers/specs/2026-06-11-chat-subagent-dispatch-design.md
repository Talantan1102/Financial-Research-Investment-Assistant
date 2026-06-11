# Chat 模式子 agent 派发与通信设计

- 日期：2026-06-11
- 状态：设计定稿，待写实施计划
- 关联：
  - 上游架构：`2026-06-05-chat-loop-redesign-design.md`（裸 while 工具循环本体，本设计在它之上加一个工具）
  - 决策依据：`dashboard/data/reports/subagent-dispatch-survey.yaml`（子 agent 派发 7 决策调研）
  - 后续评测：`2026-06-08-chatloop-eval-blueprint-design.md`（本设计的评测尺子挂这里）
  - 隔离对象：研报图 `backend/app/orchestration/research_graph.py`（深度研究，与本设计彻底隔离）

---

## 一句话总纲

在 chat 的裸 while 工具循环上加**一个只读扇出原语** `dispatch_subagents`：主 AI 识别出"一堆互不依赖、各自只用查的小任务"时，一次把它们派给几个临时**子循环**（同一个 `ToolLoop` 类、换一组受限依赖构造），子循环干净隔离 context、fast 档、硬护栏，**并发跑、同步收齐**，主 AI 收回每个子循环的**原文摘要**自己综合进当轮回答。它填补的是"对单 AI 太重、又不值得升级成研报"的中间档；它与深度研报**彻底隔离**。

---

## 二、背景与动机

### 2.1 现状缺口：中间档是空的

chat 现在是单 AI 单循环：调一个工具 → 看结果 → 再调 → 最多 12 圈（`gates.py` `max_steps=12`，注释锚定"六只持仓约五圈"）。对"一堆互不相干的只读小任务"，这一个 AI 只能一件件串着查，又慢、又把所有中间结果堆进同一个上下文窗口。

项目已有两条"把活甩出去"的路，中间缺一档：

| 形态 | 重量 | 用户确认 | 进程 | 产出 | 适合 |
|---|---|---|---|---|---|
| 升级→深度研究（已有） | 重 | **要**确认门 | 独立 pipeline | 整份研报落库 | "帮我做份茅台尽调" |
| 记忆 Path B / 监控（已有） | 后台 | 无 | Celery | 与当轮无关 | 跨 turn 抽取、盘中告警 |
| **chat 内 fan-out 子循环（本设计）** | 轻 | **不**确认 | 同 chat worker | 就地综合进当轮答 | "茅台五粮液宁德比一比" |

### 2.2 三个驱动场景（皆只读 fan-out）

用户确认的三类驱动负载，本质都是"N 个同构独立的只读子任务"，因此**一个通用原语覆盖三类**，不为每类写领域工具：

1. **多标的对比**——"茅台、五粮液、宁德比一比"：每只标的的取数互不依赖。
2. **多源广度检索**——"怎么看光伏"：KB / 新闻 / 泛网三源各自独立预取。
3. **持仓全景体检**——逐只持仓跑"现价+估值+新闻+信号"同构检查；标的数不定，正是 `max_steps=12` 的设计锚点场景。

### 2.3 为什么只读 fan-out 恰好安全

调研报告两篇对立长文（Anthropic《放心并行》vs Cognition《Don't Build Multi-Agents》）唯一的共识判据：**能并行的本质 = 任务可切成互不依赖、不写同一份共享状态的只读块**。三个驱动场景全落在这个窄窗口里——所以没有 Flappy Bird 式拼接冲突。写类活（估值→辩论那种有依赖的）继续留在主循环串行，本设计碰都不碰。

---

## 三、隔离铁律（chat 内派小弟 ⫫ 深度研报）

> **本设计的 `dispatch_subagents` 子循环完全活在 chat 这一轮里，与深度研报是两个世界，编排上互不调用。**

| | chat 内派子循环（本设计） | 深度研报（已有） |
|---|---|---|
| 在哪跑 | chat 这一轮的 worker 进程内，同步起落 | 独立 pipeline，另一条触发 |
| 用户确认 | **不要**，主 AI 自主派 | **要**，`offer_deep_research` → 确认门 → 才跑 |
| 用哪套机器 | **复用 chat 裸 while `ToolLoop`**（换只读受限依赖） | **LangGraph 研报图**（Planner/Collector/Analyst/Writer/Critic + 估值 + 多空辩论） |
| 时长 | 秒级 | 分钟级 |
| 产出去向 | 摘要**就地综合进这条 chat 回答**，不落研报表 | 落 `research_reports` 表 + 往 chat 塞研报锚点消息 |
| "收齐"是谁的事 | chat worker 里这批子循环 `gather` 等齐——纯 chat 这边 | 研报图内部自己的扇出/收集——与本设计无关 |

**防串门硬保险**：子循环是只读白名单，**拿不到 `offer_deep_research`**——从权限上堵死"chat 子循环漏进研报世界"。能提议升级的只有主 AI，且也只发信号、仍需用户确认。

**唯一共享（诚实标注）**：两个世界共用最底层的**只读数据工具**（`get_stock_quote` 等 MCP 工具背后同一数据源）与**留痕底座**（TraceService）。那是"同一份水电"，非编排耦合——控制流、生命周期、产出去向全隔离。

这条隔离作为**回归守卫不变量**写进评测（见 §10）。

---

## 四、核心原语：`dispatch_subagents`

### 4.1 工具定位与签名

一个 **in-process 工具**（`InProcessTool`，因为要碰 turn 状态做预算回滚），主循环 LLM 一次调用、传入一组子任务：

```
dispatch_subagents(reason: str, subtasks: list[SubtaskSpec]) -> ToolResult
```

`SubtaskSpec`（**LLM 填**的部分——一张固定字段任务表，不是自由文本）：

| 字段 | 谁填 | 含义 |
|---|---|---|
| `goal` | LLM | 这个子任务要查什么（一句话目标） |
| `target` | LLM | 锁定的对象：ts_code / 信息源标识（"茅台 600519" / "新闻源"） |
| `output_hint` | LLM | 想要的产出形状（"现价+近一年营收增速+一句话风险"） |
| `boundary` | LLM | 边界（"只看近一年"、"不含港股"） |

harness 补全的部分（**不交给 LLM**，护栏）：`subtask_id`、`tool_scope`（只读白名单）、`tier="fast"`、`max_steps=4`、`budget_cny` / `budget_tokens`（切片÷个数）。

> 固定字段表是冲着 MAST 头号失败（41.8% 来自"分派指令没说清"——Anthropic 早期只说"研究芯片短缺"导致子 agent 重复劳动+留窟窿）去的：逼着把目标/对象/格式/边界填清。

### 4.2 五道护栏

| 护栏 | 值 | 防的是 | 对应调研维度 |
|---|---|---|---|
| 深度 1 / 禁递归 | 子循环 tool_hub **不含** `dispatch_subagents` | 无限嵌套失控 | ⑤ 深度终止 |
| 只读 | 子循环 tool_hub 只挂只读数据工具 | 并行写冲突（Flappy Bird） | ②③ |
| fast 档 | 子循环 `tier="fast"` | 贵 lead + 便宜 worker | ⑥ 模型分档 |
| 步数闸 4 | 子循环 `GateConfig(max_steps=4)` | 单个子循环跑飞 | ⑤ |
| 预算切片 + 个数上限 | 派前预留一块总预算；`N ≤ 6~8`，超了分批 | over-spawn（Anthropic 真为简单问题 spawn 50 个） | ⑤ |

### 4.3 触发判据（写进工具 description）

照搬 Anthropic"按难度定数量"，由主 AI 临场判断 + description 承载（不设单独路由节点）：

- 单个事实（"茅台多少钱"）→ **不派**，自己一圈答掉。
- 2~几个互相独立的东西 → **派这么多个**（典型 2-6）。
- 大到要做整份尽调 → **不派**，改 `offer_deep_research`。
- **硬规矩**：子任务之间有依赖（B 要先看 A 的产出，如"先估值再辩论"）→ **绝不并行派**，留主循环串行。判据一句："B 要不要先看 A 的产出？"

个数上限设 6~8（覆盖常见持仓数）；超出分两批派（仍远优于 12+ 圈串行）。

---

## 五、子循环的构造（复用 `ToolLoop`，纯依赖注入）

子循环 = **同一个 `ToolLoop` 类**，用一组受限依赖构造。`ToolLoop.__init__`（`loop.py:52-64`）全可注入，零框架：

| 构造参数 | 主循环 | 子循环 |
|---|---|---|
| `tool_hub` | 全量（核心6+延迟8+search_tools） | **只读子集**（见下），无 search_tools、无渐进披露 |
| `gate_cfg` | `GateConfig()`（max_steps=12, ¥0.10, 120k） | `GateConfig(max_steps=4, max_cny=切片, max_tokens=切片)` |
| `tier` | `"balanced"` | `"fast"` |
| `seq_counter` | turn 级共享实例 | **同一个共享实例**（否则前端单 last_seq 排序崩，`events.py:41-43` 明令） |
| `emit` | runner 注入 | **同一个 emit，外包一层 lane 注入适配器**（见 §6.3） |
| `steer_source` | `RedisSteerSource` | **None**（插话不进飞行中子循环） |
| `cancel_event` | turn 级 | **同一个**（用户取消整轮时子循环一起断） |
| `context_deps` | 全量 | 精简（无 persona/skill_listing/记忆，见下） |

**子循环的初始 `ChatLoopState`**：一张白纸——只有一条 user 消息 = 渲染后的 `SubtaskSpec`（目标/对象/格式/边界）。**不含**主对话历史、兄弟子任务、用户记忆/画像。这是"干净隔离 context"（Anthropic 侧），敢给白纸**正因为任务只读且互相独立**。

**子循环的只读工具子集**（`tool_scope`）：`get_stock_quote` / `get_financial_statements` / `kb_search` / `get_news` / `web_search` / `get_market_indicators` / `get_corporate_actions`。**排除**：`compare_stocks`（它自己就是扇出工具，子循环是扇出单元，避免嵌套）、`memory_*`（白纸无记忆需求）、`load_skill` / `run_skill_script`（纯检索不需方法论）、`offer_deep_research` / `dispatch_subagents`（防串门 + 禁递归）。子循环工具少（约 7 个），全给完整 schema，不需渐进披露。

**新增装配件 `SubagentFactory`**：在 `worker_wiring.build_turn_components` 时构造、注入 `dispatch_subagents` 工具。它闭包持有：`llm`、只读 `tool_hub` 工厂、`emit`、`seq_counter`、`cancel_event`、tier 策略、gate 模板。`factory.spawn(subtask) -> SubagentResult`：构造子 `ToolLoop` + 白纸 `ChatLoopState` → `await loop.run()` → 抽取 `SubagentResult`。

---

## 六、通信三层

### 6.1 主 ↔ 子：派活与回收（进程内对象，非文件）

**派活**：`SubtaskSpec`（§4.1），进程内 Pydantic 对象直接传入子循环，不落盘、不走网络。

**回收**：每个子循环返回 `SubagentResult`：

```
SubagentResult:
  subtask_id: str
  summary: str            # 子循环自己的终答原文（verbatim）
  evidence_refs: list[str]# 证据出处：缓存 ref / 源标识
  status: "ok" | "partial" | "failed"
  gap_note: str | None    # 部分/失败时说明缺了什么
  tokens_spent: int
  cost_cny: float
  steps_used: int
  tier: str
```

**两条聚合铁律**（对应调研维度 ④）：

1. **原文直传，不复述**：`summary` 是子循环自己的终答原文，主 AI 原文照收再综合——避免 LangChain 实测的"电话游戏"层层转述失真（forward 原文带来近 50% 提升）。主 AI 是**综合者**（synthesizer），不是转述者。
2. **开放文本不投票**：对比/检索是开放式产出、没有"同一个标准答案"，由主 AI 综合收口，**不做 majority voting**。

**窗口 vs 缓存分流**：只有 `summary + evidence_refs` 进主循环窗口；子循环看过的**大块原始资料**走现有 `ToolResultCache`（按 ref 编号），主 AI 要细节时调 `read_cached_result(ref)` 取回。即"摘要进窗口、全文进缓存按需取回"——保持主窗口精简。

### 6.2 子 ↔ 子：不通信（设计结论）

并行子循环**互相看不见、互不通信**。这不是缺功能，是让并行安全的设计结论：任务本就独立（查不同标的/不同源），无可协调之物。一旦某活需要兄弟互看产出（写类、拼一个共享产物），它就**不适合本工具**——那是深度研报的活（共享完整 trace、单线程）。

### 6.3 子 → 前端：lane 进度可见性

- 子循环每一步发**和主循环同一条事件流**（共享 `SeqCounter`），每条事件 `data` 里带 `lane = subtask_id`。
- **emit 适配器**：因 `LoopEvent` frozen，给每个子循环传一个包装过的 emit——`event.model_copy(update={"data": {**event.data, "lane": sid}})` 后转发；不动 `ToolLoop` 内部。
- **两个新事件类型**：`dispatch_start{batch_id, n, subtasks:[{subtask_id, goal_brief}]}`、`dispatch_end{batch_id, results:[{subtask_id, status}]}`。子循环内部复用现有 15 种事件类型（`step_start`/`tool_start`/`tool_end`/`token`…），靠 `lane` 区分。
- 前端在 `dispatch_start`…`dispatch_end` 之间渲染 **N 条并行进度条**（仿 Claude Code 折叠子任务进度）。
- **插话**：`steer_source=None` 的子循环收不到插话；用户中途插的话排队在主循环，等这批收齐后的下一圈并入。

---

## 七、运行期语义

### 7.1 失败兜底（照搬 ToolHub 硬契约：绝不抛异常）

- 子循环超时/崩/吐垃圾 → 包成 `SubagentResult{status:"failed", gap_note}`，**不抛异常**。`asyncio.gather(return_exceptions=True)`，3 个挂 1 个照样回 3 份。
- 子循环撞自己的步数/预算闸 → 逼它基于已查到的 `force_conclude` → 回 `{status:"partial", summary}`。**永远回点东西，绝不静默丢**（项目"快速失败、不静默兜底"硬规则）。
- 收齐后**主 AI 自己判断**缺口处置：拿成功部分作答+标注缺口 / 再派一次补 / 提议升级。**工具自身不自动重试**（重试与否是主 AI 决策，且要守预算；调研维度 ⑦ 警告无脑重试，虽只读重试安全，仍交主 AI 决断）。

### 7.2 预算账

- **派前预留**：从当轮总预算（¥0.10 / 120k token）划一块给这批；划不出 → 少派/不派/降级为主循环自查。
- **子循环各有小闸**：切片 ÷ 个数；单个子循环烧超自己收尾，**烧不穿主预算**。
- **收齐回滚**：`dispatch_subagents`（in-process，`run_with_state`）把子循环实际烧掉的 token/钱**加回 `state.budget_spent_*`**——主循环预算闸下一圈照常生效。
- **整批只算主循环 1 步**：派 6 个子循环，主循环可能总共才两三步，**不撑爆 12 步闸**——这正是它比"主 AI 自磨 12 圈"省的地方。

### 7.3 同步收齐与终止

- 一次 `asyncio.gather` 等齐整批才往下——与项目现有 critic 八维、多空辩论"同时跑、等全部返回"完全同款，不引新花样。
- 收齐语义**只属于 chat 这边的子循环**（§三隔离铁律），与研报图内部扇出零耦合；最慢拖的也只是 chat 这一轮（子循环秒级）。

---

## 八、留痕（span 树 + 专用审计表）

采用"span 树 + 专用审计表"双层（评估时选定，非最省的纯 span 档、亦非最全的原始产出落库档）。

### 8.1 span 树（吃现有 TraceService，永久落 PG）

`TraceService.write_span` 的 `Span` 本就带 `inputs` / `outputs` / `parent_id` / `metadata`（`trace_service.py:47-75`），`stream_step` 已接受 `parent_span_id` 往下传（`llm_service.py:85,161`，`test_stream_step_parent_span_id_propagated` 守着）。三层树：

- **派发批次 span**：`name="dispatch_subagents"`，`parent_id=`主 turn span，`inputs={reason, n, scenario_type}`，`outputs={n_ok, n_partial, n_failed, total_tokens, total_cost}`。
- **子循环 span**：`parent_id=`批次 span，`inputs=`完整 `SubtaskSpec`，`outputs=`完整 `SubagentResult`。
- **子循环内 LLM 调用 span**：`parent_id=`子循环 span（`stream_step` 传 `parent_span_id`）。

→ `主turn → 派发 → [子循环A → 它的几次LLM调用, 子循环B, …]` 一棵树，永久在 PG，`query_spans({request_id})` 一查即出，`TraceTree.from_spans` / `scripts/trace_view.py` 可打印。

### 8.2 专用审计表 `subagent_dispatch_runs`（跨次统计 / 上漫板 / 做 eval 断言）

span 树擅长看单棵，不擅长跨多次聚合（metadata 是 JSON 无索引）。新增一张 ORM 表，**一行 = 一个子循环**，批次字段去规范化到每行（一个 model，`create_all()` 幂等自动建，遵 v0.9.x 不引 alembic 约定，对齐 PR-B 的 `TraceSpanRow`/`EvalResultRow`/`BacktestRunRow` 先例）：

| 列 | 类型 | 索引 | 说明 |
|---|---|---|---|
| `id` | PK | | |
| `batch_id` | str | ✓ | 同一次派发的子循环共享，聚合用 |
| `parent_request_id` | str | ✓ | 关联 trace |
| `turn_id` | str | | 所属 chat turn |
| `scenario_type` | str | ✓ | 多标的对比/多源检索/持仓体检 |
| `subtask_id` | str | | |
| `goal_packet` | JSON | | 完整 `SubtaskSpec` |
| `tool_scope` | JSON | | 给了哪些只读工具 |
| `result_summary` | text | | |
| `result_refs` | JSON | | |
| `status` | str | ✓ | ok/partial/failed |
| `gap_note` | text | | |
| `tokens` / `cost_cny` / `steps_used` / `duration_ms` | num | | 按子循环归因 |
| `tier` | str | | |
| `created_at` | ts | ✓ | |

→ 支撑"所有失败/部分的派发""按场景的平均每子循环成本/耗时""误派率"等查询，喂漫板面板（补调研 gaps 点名的"派发可观测性·按子 agent 归因，学 Magentic stall 计数"），并做 §10 的离线 golden 断言。

---

## 九、与四闸 / 窗口 / 台账的整合

- **四闸**：派发整批算主循环 1 步（步数闸）；子循环 token 回滚进主账（预算闸）；子循环有独立台账（不并入主台账，保持主循环打转检测/烧签名干净）。
- **窗口四区**：派发结果以**一条 tool 消息**进"本 turn 轨迹区"（`summary+refs`）；大块全文进 `ToolResultCache`，受现有降级保护逻辑管辖。稳定前缀区/历史区不受影响。
- **台账**：`dispatch_subagents` 这次调用本身进主 `ToolLedger`（一条 entry，供去重/打转/升级物料）；子循环各自的台账独立，仅供留痕与 §8 审计表。

---

## 十、评测（打 MAST 41.8% 分派质量靶）

挂 `2026-06-08-chatloop-eval-blueprint`，拿 §8.2 审计表做离线 golden 断言：

1. **该不该派（双指标）**：该派时派（"比3只票""逐只体检持仓"）/ 不该瞎派（"茅台多少钱"单事实别扇出）——对齐工具选择 eval"该调时调、不该调时弃权"。
2. **派得对不对**：子循环数对、是否全只读、每个是否只锁一只标的/一个源、边界给清。
3. **不变量回归守卫**：子循环深度恒为 1（无递归）、未碰写工具、未碰 `offer_deep_research`（§三隔离铁律的自动化守卫）。
4. **差分对照**（复用持仓演化那套差分测试）：同一输入"有派 vs 无派"比产出质量/延迟/token，验证 fan-out 真省真好。

---

## 十一、7 维映射（作品叙事骨架）

| 调研维度 | 本设计决策 |
|---|---|
| ① 谁来路由 | 主 AI 临场判断 + 工具 description 写"难度→派几个"，**无单独路由节点** |
| ② 并行/串行 | 只读独立→并行派；有依赖→留主循环串行；判据"B 要不要先看 A" |
| ③ context 隔离 | 干净白纸（Anthropic 侧）——只读独立才敢给白纸，无 Flappy Bird |
| ④ 结果聚合 | 主 AI 当综合者，子循环摘要**原文直传**防电话游戏，开放文本**不投票** |
| ⑤ 深度/终止 | 深度 1 禁递归 + 步数闸 4 + 预算切片 + 个数上限 6-8 + 同步等齐 |
| ⑥ 模型分档 | fast 子循环 + balanced/deep 主 AI。**诚实标注**：当前三档解析到同一模型，分档留口待多模型整体接上（同项目现有 tier 现状） |
| ⑦ 失败/重试 | 包不抛 + 缺口说明 + fail loud；只读使重试安全，但工具不自动重试、交主 AI 决策 |

每维都有可溯源的 trade-off——简历可讲的是"对 7 个工业决策逐个拍板并标注边界"，而非"堆了个多 agent"。

---

## 十二、明确不做什么（非目标 / 留口）

YAGNI，且都是诚实的能力边界，不是遗漏：

- ❌ **异步流式 / 早停慢子循环**——escape hatch，这版同步等齐（调研维度 ⑤ 提过）。
- ❌ **子循环之间通信**——写类活才需要，那是深度研报的活。
- ❌ **子循环递归**（派子循环的子循环）——只一层。
- ❌ **插话进飞行中子循环**——排队等下一圈。
- ❌ **真·多模型分档**——口子留好，待项目多模型整体接上才真省。
- ❌ **学习型拓扑**（GPTSwarm/DyLAN 把连接当可优化图）——坦诚标为能力边界，不碰。
- ❌ **原始产出永久落库**（留痕最全档）——留口，按需再开。
- ❌ **监控告警→chat 追问**——另一个未接口子，不在本设计。
- ❌ **Contract Net 拍卖 / 黑板式分派**——LLM 时代少用，不走。

---

## 十三、影响面（预估改动，细化留给实施计划）

- 新增 `backend/app/chatloop/subagent.py`（`SubtaskSpec` / `SubagentResult` / `SubagentFactory` / `dispatch_subagents` 工具）。
- `worker_wiring.py`：`build_turn_components` 构造 `SubagentFactory` + 只读 tool_hub 工厂，注册 `dispatch_subagents`。
- `events.py`：加 `dispatch_start` / `dispatch_end` 两事件类型。
- `tool_docs.py`：`dispatch_subagents` 进核心/延迟组之一 + description（含触发判据）。
- 新增 ORM `subagent_dispatch_runs`（`create_all()` 自动建）+ 写入点。
- 前端：`dispatch_start`/`dispatch_end` 渲染 N 条 lane 进度条。
- 评测：golden case + 不变量守卫 + 差分对照。
- 漫板：派发可观测性面板（读 `subagent_dispatch_runs`）。

---

## 十四、开放问题（实施期定）

- 个数上限确切值（实施定为 8）与分批策略的具体阈值。
- 预算切片占当轮总预算的比例（实施定为剩余预算 × 0.6 均分到每个子循环，单子循环下限 ¥0.005）。
- ~~`dispatch_subagents` 归核心组还是延迟组~~ **已由浏览器 e2e 实测定为核心组**：deferred 下模型逐只串行查、从不扇出，且 thin 条目不暴露 subtasks 项结构（goal/target/…）无从填；升 core 后完整 schema 常驻，模型按指示即正确扇出。与 run_python 同款 verify 驱动修正。
- `scenario_type` 是 LLM 标注还是 harness 按子任务形状推断（实施暂留 NULL，审计行已落，分类后补）。

## 十五、实施落地补记（2026-06-11）

- **留痕收敛为审计表**：B 档原设想"span 树 + 审计表"；实测发现 chat turn 现状是每圈一个 `parent_id=None` 的扁平 span（`TraceTree.from_spans` 要求单根，当前 chat turn 已拼不成树），真要成树需先给整个 turn 建根 span（独立重构）。故本期留痕 = 审计表 `subagent_dispatch_runs`（每子循环完整输入/输出/工具调用/成本永久落 PG，可查可断言），span 树成树留 follow-up。
- **前端 lane 可见性修正**：DispatchLanes 初挂在 messagesRegion 末尾会溢出被输入框遮挡，移入可滚动 chatContainer + 自包含卡片样式后正常显示（e2e 实测三条并行进度条可见）。
- **e2e 实测结果**：浏览器发"派 3 子助手查茅台/五粮液/宁德"→ dispatch 扇出 3 子循环并发 → 前端渲染 3 条 lane（带实时取数计数）→ 审计表落 3×3=9 行（3 批次）→ 主 AI 综合。
