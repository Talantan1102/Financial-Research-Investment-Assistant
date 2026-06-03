# 设计：Chat 命令系统（Slash Commands + 气泡操作）

> 状态：需求定稿（pre-plan）。落地前据 §6 PR 切分切成正式 plan。
> 调研依据：`docs/superpowers/specs/2026-06-02-chat-slash-tool-mechanism-research.md`（底座可行性、参考实现、改动清单）。
> 看板锚点：能力卡 `tool.chat_slash_command`（manual / planned）。

---

## 1. 目标与范围

给 chat 加一套**显式命令系统**，让用户在 power-user 场景绕过 LLM 自动路由、直接指定动作。定位为 minimalism escape hatch（见 `product-minimalism-default`），不破坏 chat-first 自动路由的默认体验。

特性由**两条独立链路 + 一组气泡操作**组成。三者机制不同，必须分开设计、分开验证。

---

## 2. 链路一 · Forced-Tool 命令

走调研报告 §4 的 `forced_tool` 后端路径：前端把 `forced_tool_name`(+`forced_tool_args`) 塞进 `POST /api/v0/chat`，后端 `forced_tool_router` 分支跳过 LLM planner，直接构造 `ToolCall` 走现有 `tool_node`，**复用现有 `tool_start/tool_end/tool_error` SSE 事件和 `ToolCallCard` 渲染，零新事件类型**。

| 命令 | MCP 工具 | 参数 | 批次 |
|---|---|---|---|
| `/quote <ts_code>` | get_stock_quote | 单 ts_code | 1 |
| `/fin <ts_code>` | financial_statements | 单 ts_code | 1 |
| `/indicators <ts_code>` | market_indicators | 单 ts_code | 1 |
| `/actions <ts_code>` | corporate_actions | 单 ts_code | 1 |
| `/news <query>` | get_news | 单 query | 2 |
| `/kb <query>` | kb_search | 单 query | 2 |
| `/web <query>` | web_search | 单 query | 2 |
| `/compare <code1> <code2> ...` | compare_stocks | 多 ts_codes → 引导式 modal | 3 |

- 工具命名以 **MCP 8 chat 工具**为唯一 SoT（调研 §6.2 口径问题：不用 `tools-reference.md` 的 13 底层实现）。
- 参数收集：单参内联（`/quote 600519.SH`，提交前 regex 提取）；多参走 modal，复用 `EscalationConfirmDialog` 模式。
- 校验复用 `nodes.py` 的 `args_schema.model_validate()`；错误走现有 `tool_error` → 重试按钮。

**语义决策（调研 §6.1 开放问题）**：forced 路径为「**这一轮只调这一个工具并直接出结果**」，不再交回 supervisor。理由：确定性、可复现、cassette 简单。需 supervisor 接管的场景仍走自然语言。

---

## 3. 链路二 · 系统/会话命令

前端 + session 持久化层，**不走工具链**。复用已有 session 持久化 / title 异步生成 / LangGraph checkpoint resume 底座。

| 命令 | 行为 | 复用底座 |
|---|---|---|
| `/tools` | 弹命令清单 + 参数提示 | 新增 `GET /api/v0/tools`（MCP 8 工具元数据），同时驱动 slash 菜单 |
| `/model` | 切换模型（**全局生效**，非仅本会话） | LLMService provider 选择 |
| `/resume` | 回退到本会话过往某个 **turn** | LangGraph checkpoint（turn 级，见决策 ②） |
| `/branch` | 从某 **turn** 新开对话分支 | session 持久化 + checkpoint fork |
| `/export` | 导出当前对话为 Markdown/报告 | Reports 模块 |

**已定决策：**
- **① `/model` 全局生效**。切换即改全局默认模型，不是 per-session。注意：会影响已有 session checkpoint 的可复现性（旧 turn 用旧模型录的 cassette/checkpoint，resume 后续 turn 走新模型），这是接受的代价——用户显式切换即知情。
- **② 回退/分叉粒度 = turn 级**。`/resume`、`/branch`、以及气泡 `retry`/`edit` 全部以一个完整 turn（用户消息 → 工具调用 → 最终回答）为原子单位，不暴露 turn 内部的消息级粒度。直接吃 LangGraph 现成 per-graph-run checkpoint，与 sidebar 会话列表心智一致。代价：做不到「保留工具结果只重写回答」（需消息级，本期不做）。

### 3.1 `/resume` 与 `/branch` 技术实现（LangGraph 原生 time-travel）

**结论：全部走 LangGraph checkpointer 原生能力，现有底座已覆盖 ~80%。**

现有底座（已就绪，无需新建）：
- `postgres_checkpointer.py` 用官方 `AsyncPostgresSaver`，每个 turn 自动落一个 checkpoint 到 PG `langgraph_checkpoints` schema。
- `thread_id = f"{user.id}:{session_id}"`（`chat.py:461`）——同一会话所有 turn 串在一个 thread，每 turn 一个 `checkpoint_id`。
- `chat_tasks` 表已存 `langgraph_thread_id` / `langgraph_checkpoint_id` / `parent_task_id` 父子链。
- `POST /api/v0/chat/retry/{task_id}`（`chat.py:915`）已用 `resume_checkpoint_id` 让 Celery worker 从 checkpoint 续跑——但当前仅限 error/partial/cancelled task。

**`/resume`（回退到历史 turn）**：
1. 列历史：`graph.aget_state_history(config)` 返回该 thread 全部 checkpoint，每个对应一个 turn（`state.config[...]["checkpoint_id"]` + `state.values`）。turn 级粒度天然对上。
2. 回退：在 config 注入选中的 `checkpoint_id` → `{"configurable": {"thread_id": ..., "checkpoint_id": "<选中 turn>"}}`，从该点续跑，其后 turn 被截断。
3. 落地：把现有 retry 端点从「仅 resume 失败 task」放宽到「resume 任意历史 turn」；**新增** `GET /api/v0/chat/{session_id}/history` 暴露 `aget_state_history` 结果给前端选择。

**`/branch`（从历史 turn 分叉）**：
1. fork：`graph.aupdate_state({"configurable": {"thread_id": ..., "checkpoint_id": "<历史 turn>"}}, values={...})` 从历史点写入新 state，LangGraph 自动岔出新 checkpoint，**原线完整保留**。
2. 落库：分支建为**新 session**，`chat_sessions` 加 `parent_session_id`（指向原会话）+ fork 起点 checkpoint_id——正是 sidebar 树状缩进（决策 ③）所需的父子关系。`parent_task_id` 链已是同模式。
3. `edit` 气泡 = `aupdate_state` 时替换被编辑的 user message 即「编辑即开分支」。

**要新写的增量**：
| 能力 | LangGraph API | 现状 |
|---|---|---|
| 列历史 turn | `aget_state_history()` | 新增 `GET /chat/{sid}/history` 端点 |
| 回退到某 turn | config 传 `checkpoint_id` | 改造现有 retry 端点放宽状态约束 |
| fork 分支 | `aupdate_state()` | 新写（API 现成，落库新增字段） |
| 分支父子关系 | — | `chat_sessions` 加 `parent_session_id` + fork checkpoint_id |

---

## 4. 气泡操作（非 slash，消息气泡上的小按钮）

不进 slash 菜单，作为消息气泡内联按钮：

- **retry** — 重跑最后一个 turn（含工具调用，turn 级，见决策 ②）。复用现有 SSE 重发链路。
- **edit** — 编辑用户消息并从该 user 消息所在 turn 重跑。与 `/branch` 语义耦合：**编辑即开分支**（保留原对话线，新分支从该 turn 分叉）。

---

## 5. 实现细节决策（已定）

1. **slash 菜单不分组**：工具命令与系统命令在下拉里平铺，不做分块小标题。
2. **菜单组件用 cmdk**：headless 开源库，自带键盘导航/模糊搜索/a11y，不换编辑器、最小侵入现有 textarea。
3. **`/branch` 分支在 sidebar 树状缩进展示**：新分支作为子项缩进挂在父会话下，呈现父子层级（需 sidebar 支持缩进/折叠），非平铺。

---

## 6. 显式不做（本期）

`/stop`、`/rename`、`/cost`、`/memory`、`/persona`、`/search`、`/share`。理由：minimalism，先验证两条链路 + 气泡操作的核心价值，其余按 dogfood 反馈再议。

---

## 7. PR 切分建议

- **PR-1（后端，可独立验证）**：`ChatRequest` 加 `forced_tool_name/args` + `forced_tool_router` + `GET /tools` 端点 + L0/L1 e2e。curl 即可验，前端未动也能跑。
- **PR-2（前端 MVP）**：cmdk slash 菜单 + `/` 触发检测 + 单参内联 + 复用 `ToolCallCard`，先开批次 1 的 4 个单 ts_code 工具 + `/tools`。
- **PR-3（系统命令）**：`/model` + `/export`；`/resume` + `/branch` 因依赖 checkpoint 语义决策（§5.2）单独成 PR。
- **PR-4（气泡操作）**：retry + edit 气泡按钮（edit 依赖 §5.2 的 branch 语义）。
- **PR-5（增强）**：`/compare` 多参 modal + `web_search/kb_search/get_news` query 类。

---

## 附：依赖与风险沉淀

- 测试：forced 路径补 L0/L1（eager）e2e，cassette 较简单（无 LLM planner 调用）。注意 `db_session` rollback isolation 与 Celery eager fixture 模式。
- 权限：memory 6 工具本期不开放（调研 §6.4）。
- 命名口径：菜单/`GET /tools` 以 MCP 8 工具为 SoT。
