# 调研报告：在 chat 中加「/工具」机制（用户对话中主动调用指定工具）

> 生成方式：`research-slash-tool-mechanism` workflow（6 路并行调研 = 3 本仓库架构映射 + 3 开源参考项目），2026-06-02。
> 本文为**调研/决策依据**（pre-spec）。落地前建议据「下一步」切成正式 spec + plan。
> 证据均带 `file_path:line`，核心后端锚点已人工 spot-check 复核。

---

## 1. 结论速览

**可行，且改动可控。** 本项目已经具备「/工具」机制的全部底座：后端是 LangGraph supervisor + MCP ToolRegistry（工具元数据/参数 schema 现成），SSE 协议已有 `tool_start / tool_end / tool_error` 事件且前端 `ToolCallCard` 已能渲染工具调用状态。缺的只有两块：(a) 前端输入框没有任何 slash/补全机制（`InputArea.tsx` 是纯受控 textarea）；(b) 后端没有「强制调某工具」的 `tool_choice` 路径——当前 `ChatPlanner` 完全由 LLM 自主路由，只有 whitelist 过滤幻觉工具名。

**推荐最小可行方案（MVP）**：前端在现有 textarea 之上叠一个 **cmdk** headless 下拉补全菜单（不换编辑器、最小侵入），用户打 `/` 弹工具列表 → 选中后把 `forced_tool_name`（+ 可选 `forced_tool_args`）塞进现有 `POST /api/v0/chat` 请求体；后端在 `planner_node` 前加一个 `forced_tool_router` 分支，命中则跳过 LLM planner、直接构造一个 `ToolCall` 走现有 `tool_node`，**完全复用现有 `tool_start/tool_end` SSE 事件和 `ToolCallCard` 渲染**，无需新事件类型。第一批先开放参数最简单的工具（单一 `ts_code` 或单一 `query`）。

这与本项目两个参考实现高度同构：**LibreChat 的 `SkillsCommand`**（`$` 触发 + `pendingManualSkillsByConvoId` 作为 per-message 结构化通道）和 **Vercel AI SDK 的 `toolChoice:{type:'tool',toolName}`**（硬强制指定工具）——前者是 UI 模式，后者是强制机制，我们的方案正是二者的结合。

---

## 2. 本项目现状

### 2.1 前端：输入 → SSE → 渲染链路

完整链路（消息流）：
- 发送：`InputArea.tsx:79-84` `send()` → `props.onSend(text)` → `ChatPane.tsx:61-67` → `useChatSSE.sendMessage(text)`（`useChatSSE.ts:197-319`）构造 `POST /api/v0/chat` body（`session_id` + `message`）。
- 双协议分流：`useChatSSE.ts:241-267` 看响应 `content-type`——`application/json` 走 Plan 2（返 `{task_id, session_id, stream_url}`，再 `GET /chat/stream/{tid}`），否则 Plan 1（直接 streaming）。
- 消费：`useChatSSE.ts:84-150` `consumeStream()` 用 `TextDecoder` 按 `\n\n` 分帧 → `parseFrame()` 解 JSON → 按 `ev.type` 分发；`token` 走 typewriter 累加 `streamingDraft`，`done/error` 排空后 `dispatchEvent()` 更新 store。
- Store：`store/current-chat.ts:135-163` `dispatchEvent()` switch：`token`→累加、`done`→`flushDraftAsMessage()` 入 `messages`、`cost_update`→更新成本。
- 渲染：`ChatPane.tsx:45-59` 用 `pendingMessage` 实时显示打字；`MessageList.tsx:30-42` `MessageRouter` 按 `message_type` 路由，`tool_call` → `ToolCallCard`。

工具调用渲染（已存在，可直接复用）：
- 事件结构：`types/chat.ts:49-66` `ToolStartEvent{type, tool_name, tool_args, call_id}` / `ToolEndEvent{call_id, result}` / `ToolErrorEvent{call_id, error}`。
- 卡片：`ToolCallCard.tsx:59-135` 展示 `tool_name` + `status(running|success|error)` + 时间戳 + `result_summary` + 可展开详情 + error 重试按钮。

**关键缺口**：`frontend/src` 全目录**零** slash / command-palette / autocomplete 痕迹；`package.json` 无 cmdk/combobox/mention 类依赖；`InputArea.tsx` 仅 `textarea + onKeyDown(Enter 发送)`，无中途 parse 逻辑。快捷键注册点在 `InputArea.tsx:68-77`（已监听 `⌘/Ctrl+K`），`onKey()` 在 `:86-94`。

### 2.2 后端：agent 工具组装与调用

- 工具集来源：MCP 动态加载，`router/chat.py:243-267` `registry.register_mcp_client_async(mcp_client)`；`mcp_server/server.py:76-103` `build_server()` 聚合 `_CHAT_TOOL_MODULES`（8 个 chat 工具）。
- 路由方式：`ChatPlanner` 是**约束 LLM 路由，无 `tool_choice` 强制**。`chat_planner.py:230` prompt「可用工具(只能从这里选,不要编)」注入工具清单，LLM 自主选；`chat_planner.py:329-330` 用 `whitelist = set(self._available_tools)` 过滤幻觉工具名（A4）。
- 执行链路：`planner_node` → `_route_after_planner`（`chat_graph.py:62-77`）→ `tool_node`（`nodes.py:60-212`，`plan.parallelizable` 时 `asyncio.gather` 并行）→ `responder_node`。参数校验在 `nodes.py:248-250` `tool.args_schema.model_validate(tc.args)`。
- 参数 schema 来源：MCP `tools/{name}.py` 的 `TOOL_DEF.inputSchema`（如 `mcp_server/tools/get_stock_quote.py:17-30`）→ `registry.py:17-41` `_MCPToolProxy.args_schema`。

### 2.3 SSE 事件协议（已 spot-check）

- 帧格式：`router/chat.py:487-491` `event:{type}\nid:{seq}\ndata:{json}\n\n`；`seq` 用于 `last_event_id` 断线重连（`GET /chat/stream/{tid}` 支持 `last_event_id`）。
- 事件类型：`router/chat.py:127-154` `StreamEvent.type: Literal[...]` ——`token / plan / tool_start / tool_end / tool_error / skill_load / skill_execute_* / escalate_request / escalate_packet_draft / cost_update / done / error / research_*`。
- 映射：`router/chat.py:317-368` `_adapt_event()` 把 LangGraph `astream_events` 映射成 `StreamEvent`。

### 2.4 工具注册表

- `ChatRequest`（`router/chat.py:112-116`）当前仅 `session_id / message / enable_web_search / enable_kb_search`——**无强制工具字段**（已复核）。
- 两个 MCP profile（`mcp_servers.yaml` + `server.py:34-73`）：**8 个 chat_tools**（`get_stock_quote / financial_statements / market_indicators / corporate_actions / get_news / web_search / kb_search / compare_stocks`）+ **6 个 memory 工具**（`archival_memory_* / core_memory_* / recall_memory_search`）。
- **⚠ 口径不一致（开放问题，见 §6）**：MCP 暴露给 chat 的是上述 8 个聚合工具名，而 `docs/tools-reference.md` 记录的是 13 个底层 `backend/app/tools/` 实现（`get_financials / get_balance_sheet / get_cashflow / get_daily_basic / get_pe_history / get_money_flow / ...`）。两套命名需先对齐——「/工具」菜单应以 **MCP 8 工具**为准（那才是真正 wire 到 chat agent 的面）。
- 当前**无独立 `GET /tools` 端点**，工具清单只在 planner 系统提示里用。

---

## 3. 参考项目怎么做（对比表）

| 维度 | Claude Code（slash command/skill） | Vercel AI SDK | LibreChat | Open WebUI / LobeChat / assistant-ui |
|---|---|---|---|---|
| **触发与解析** | 文件即命令：`.claude/commands/<name>.md` 文件名即 `/name`，客户端输入框前缀匹配，**不走模型** | 工具调用建模为 `message.parts` 里的 `tool-<name>` typed part | `$` 触发 `SkillsCommand`（per-message 选 skill/工具）；`@` 是**切换 model/endpoint/agent/preset**，非调工具 | assistant-ui：单 `TriggerPopoverRoot` 下每个触发符（`/`、`@`）一个 adapter；LobeChat 用富文本编辑器 `lobe-editor`(Lexical) 的 `slashOption` |
| **前端菜单 UI** | `/` 弹下拉，列 `description`+`argument-hint`，前缀过滤 | 按 `part.state` switch 渲染（streaming/available/error/approval） | textarea trigger 检测 + 弹 skills 菜单 | cmdk(headless combobox：↑↓ 导航/模糊搜索/onSelect) 或 tiptap `Suggestion` 插件 |
| **工具元数据驱动 UI** | YAML frontmatter：`description / argument-hint / allowed-tools / model`；清单经 `system/init` 的 `slash_commands` 数组暴露 | 工具的 `description + inputSchema(Zod)` 既喂 LLM 又驱动 UI 与校验 | skills 注册表 → `pendingManualSkillsByConvoId` 结构化通道 | adapter 三方法 `categories()/categoryItems()/search()`；chip 携带 typed metadata |
| **强制调用某工具** | `allowed-tools` 只是**软约束白名单**（仍 LLM 选），无硬强制 | **`toolChoice:{type:'tool',toolName:'x'}` 硬强制** + `activeTools` 收窄可见子集 | 选中的 skill 作为 per-message pending 项随请求提交，后端据此约束 | （UI 层为主，强制靠后端） |
| **streaming 协议** | prompt 模板展开后注入 LLM | tool part 状态机 `input-streaming→input-available→output-available/error/approval-requested`；前端 `addToolOutput` 回填、`prepareSendMessagesRequest` 注入 `toolChoice` | 标准 SSE | SSE / data stream |

**两个最贴合本项目的范式**：
1. **LibreChat `SkillsCommand` + `pendingManualSkillsByConvoId`** —— 几乎是本项目的镜像（同样有 skill 体系、同样 textarea），证明「`$`/`/` 触发 + per-message 结构化通道随请求提交」这条路走得通。
2. **Vercel AI SDK `toolChoice` + `prepareSendMessagesRequest`** —— 给出「前端选中工具名 → 放进请求 body → 后端转成硬 `tool_choice`」的标准接法，正好补 Claude Code 软白名单做不到的硬强制。

---

## 4. 推荐方案（端到端）

### 4.1 前端
- **菜单组件**：在现有 `<textarea>` 之上叠一个 portal popover，用 **cmdk**（headless，自带 ↑↓ 导航/模糊搜索/onSelect/a11y，2-3k 项无需虚拟化）。**不换编辑器**——保留 textarea + valtio 受控模式，改动最小，最契合现架构。备选：自写 portal popover（零依赖）；若日后要 chip/富文本再上 tiptap `Suggestion`。
- **触发检测**：`InputArea.tsx` 的 `onChange/onKeyDown` 加 `value` 末段 `/^\/\w*$/` 检测开/关菜单；菜单开时把 `↑↓/Enter/Esc` 与现有 `Enter 发送` 做**优先级互斥**（菜单开 → Enter 选中而非发送）。注意现有 `isComposing`(IME) 判断要保留。caret 锚点用隐藏 mirror div 算。
- **菜单数据**：新增 `GET /api/v0/tools` 拉 MCP 8 工具元数据（`{name, description, inputSchema}`），避免命令清单与工具定义双写。
- **参数收集**（对齐产品 minimalism）：默认**内联单参**——选中后输入框续打 `/工具 600519.SH`，提交前 regex 提取；只对多字段复杂工具走**引导式 modal**，复用已有 `EscalationConfirmDialog` 模式。
- **状态**：slash 菜单状态（open/query/activeIndex/selectedTool）放 `store/current-chat.ts` 或局部 `useState`。

### 4.2 后端
- `ChatRequest`（`chat.py:112-116`）新增可选 `forced_tool_name: str | None` + `forced_tool_args: dict | None`。
- `_stream_chat`（`chat.py:403-530`）初始化 `GraphState` 时注入这两个字段。
- `chat_graph.py` 在 `planner_node` 前加 `forced_tool_router` 分支（参考 `_route_after_planner` `:62-77` 的条件路由模式）：命中 `forced_tool_name` → 跳过 LLM planner，直接构造 `ToolCall(tool_name=..., args=...)` 喂给现有 `tool_node`；否则保持现有 LLM 自主路由。
- 参数仍走 `nodes.py:248-250` 的 `args_schema.model_validate()` 校验（白名单/schema 复用，幻觉工具名天然被挡）。
- 可选优化：`registry.py` 加 `filter_by_names(names)` 给 `GET /tools` 端点用。

### 4.3 SSE 协议
- **复用现有 `tool_start / tool_end / tool_error`**，前端 `ToolCallCard` 零改动即可渲染。**不新增事件类型**。（`sse-protocol-registry` agent 曾建议加 `tool_invoke` 标记事件——非必需，仅当需要在 UI 上区分「用户强制调用」vs「LLM 自动调用」时才加，MVP 可不做。）

### 4.4 首批开放工具（按参数复杂度排序）
1. **单 `ts_code`**（最简，先做）：`get_stock_quote` / `financial_statements` / `market_indicators` / `corporate_actions`。
2. **单 `query`**：`web_search` / `kb_search` / `get_news`。
3. **多参/列表**（走 modal）：`compare_stocks`(多 `ts_codes`) 及底层带 `years_back / start_date~end_date` 的工具。

---

## 5. 改动清单（落地任务拆分）

| 层 | 文件 | 改动 | 量 |
|---|---|---|---|
| 前端 | `frontend/src/components/chat/SlashToolMenu.tsx`（新增） | cmdk/portal popover 菜单组件 | M |
| 前端 | `frontend/src/components/chat/InputArea.tsx` | `onChange/onKeyDown` 加 `/` 触发检测 + 键位互斥 + caret 锚点；props 加 `availableTools/onForcedTool` | M |
| 前端 | `frontend/src/store/current-chat.ts` | slash 菜单状态 + `forced_tool` 随 sendMessage 透传 | S |
| 前端 | `frontend/src/hooks/useChatSSE.ts` | `sendMessage` body 注入 `forced_tool_name/args`（仿 `prepareSendMessagesRequest`） | S |
| 前端 | `frontend/src/api/*` + 新组件 | `GET /api/v0/tools` client + 复杂参数 modal（复用 `EscalationConfirmDialog`） | M |
| 后端 | `backend/app/router/chat.py` | `ChatRequest` 加 2 字段；`_stream_chat` 注入 state；新增 `GET /tools` 端点 | M |
| 后端 | `backend/app/orchestration/chat_graph.py` | `forced_tool_router` 分支 | M |
| 后端 | `backend/app/orchestration/nodes.py` | （可选）`planner_node` 前置 forced 检查，复用 `tool_node` | S |
| 后端 | `backend/app/tools/registry.py` | （可选）`filter_by_names()` / 暴露 list 给 `/tools` | S |
| 协议 | —— | 复用现有 `tool_start/tool_end/tool_error`，零新事件 | — |

---

## 6. 风险与开放问题

1. **与自动路由的关系**：forced 路径**绕过** supervisor/planner 的意图理解。需明确语义——是「这一轮只调这一个工具并直接出结果」还是「以此工具为起点继续让 supervisor 接管」。MVP 建议前者（确定性、可复现）。
2. **工具命名口径必须先对齐**（§2.4 ⚠）：MCP 8 chat 工具 vs `tools-reference.md` 的 13 底层实现是两套面。菜单/`/tools` 端点应以 **MCP 8 工具**为唯一 SoT。
3. **参数校验与错误**：用户手填参数会撞到 `tools-reference.md` 记录的口径坑（如 `get_news.days_back` 死参、`years_back` 静默失效）。内联单参 + `args_schema.model_validate` 兜底，错误走现有 `tool_error` → 重试按钮。
4. **权限**：memory 6 工具是否对用户开放需决策（涉及跨 session 记忆写入），MVP 建议只开只读类金融/检索工具。
5. **测试 / cassette 影响**：forced 路径要补 L0/L1（eager）e2e；强制单工具执行的 cassette 较简单（无 LLM planner 调用），反而好录。注意 `db_session` rollback isolation 与 Celery eager fixture 模式。
6. **与「aggressive minimalism」是否冲突**：`/工具` 是给 power user 的 escape hatch，不破坏既定「不做」决策，但要克制——**默认内联单参、不引富文本编辑器、复用现有卡片与 dialog**，符合 `product-minimalism-default`。是否值得做需对齐 §7。

---

## 7. 下一步建议

1. **先做产品决策对齐**：`/工具` 是否进 roadmap？它给 power user 显式控制权（"我就要看这只票的行情"无需 LLM 绕路），但与 chat-first 自动路由理念有张力。建议按 minimalism escape-hatch 定位、小范围开。
2. **若决定做 → 写正式 spec**：`docs/superpowers/specs/` 收敛 §4 的端到端契约（`ChatRequest` 字段、`GET /tools` 形状、forced 路径语义），先解决 §6.1/§6.2 两个语义/口径问题。
3. **PR 切分建议**：
   - **PR-1（后端，可独立验证）**：`ChatRequest` 加字段 + `forced_tool_router` + `GET /tools` 端点 + L0/L1 e2e。先用 curl/测试驱动，前端未动也能验。
   - **PR-2（前端 MVP）**：cmdk 菜单 + `/` 触发 + 单参内联 + 复用 `ToolCallCard`，先开 4 个单 `ts_code` 工具。
   - **PR-3（增强）**：复杂参数 modal、`web_search/kb_search` query 类、（可选）`tool_invoke` 区分事件。

---

## 附：调研元数据
- 6 路并行 agent：3 成功映射本仓库（frontend-chat-flow / backend-agent-tools / sse-protocol-registry），3 联网参考（claude-code+ai-sdk / lobechat-ux 成功；librechat-openwebui 部分回收）。
- 综合 agent 因瞬时 403 失败，本报告由主 loop 据 5 份结构化结果 + 回收的 LibreChat 中间发现人工综合，核心后端锚点经 `grep` 复核。
