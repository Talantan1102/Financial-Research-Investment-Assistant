---
name: chat-memory Phase 1 self-managed wire ship 完
description: chat 记忆分层 Phase 1 — memory_tool_usage prompt 拼回 chat_planner, agent self-managed memory 三要素接通
type: project
---

**结论:** chat 记忆分层 Plan 1 (Phase 1 self-managed wire) ship 完, agent 在每轮对话能看到 [画像] / [便签] / 6 个 memory tools / 何时调用的教程, MemGPT-style agent-self-managed memory 范式正式接通。

**Why:**
- c5 cross-session memory ship 时留下 spec → impl gap: `memory_tool_usage.md` 模板已写但从未拼回 `chat_planner` 主 prompt(`core_memory_append.py:73` 注释明说"未来回灌 system prompt 风险")
- 本 Plan 把 self-managed 三要素的最后一步(agent loop)接通: Tools ✓(c5 6 MCP)+ Behavior guide ✓(memory_tool_usage.md)+ Loop ✓(本 Plan)
- 跟 Claude Code / openclaw / Hermes 三家工业实例的 LLM-self-managed 主路径共识对齐

**How to apply:**
- 改记忆走 agent 自己调 c5 6 MCP tools(core_memory_append/replace + archival_memory_insert/search/traverse + recall_memory_search), **不是后台批处理**
- agent 每轮看到的 prompt 头部含:Memory Tool Usage 教程 + 3 条 domain-specific save triggers(投资偏好 / 加减仓 / 表态)+ 4 条 Don't save 反例 + Self-managed loop 核心理念
- 静态区(画像 + 便签快照)用 Hermes 风的 frozen snapshot(session 起手装一次),保 prefix cache
- 失败隔离: render.py / chat_planner 都 try/except 兜底,memory 层挂了不让 chat 崩

**Anchor:**
- spec: `docs/superpowers/specs/2026-05-16-chat-memory-layering-design.md` § 7 Phase 1
- plan: `docs/superpowers/plans/2026-05-16-chat-memory-plan1-self-managed-wire.md`

**6 Task ship 范围:**

| Task | ship 内容 | commit |
|---|---|---|
| 1 | `memory_tool_usage.md` 加 3 条 domain-specific save triggers + 4 条 Don't save + Self-managed loop 段;test_system_prompt_template.py 加 2 个断言 | `5e18b9c` |
| 2 | `backend/app/memory/render.py` — `render_persona_markdown` + `render_scratchpad_markdown` 纯函数;5 L0 test | `6b951cf` + nit fix `7894f47` |
| 3 | `backend/app/agents/chat/prompt_loader.py` — 加载 `memory_tool_usage.md` 模板 + 占位符替换;4 L0 test | `b7814e0` |
| 4 | `chat_planner.ChatPlanner.__init__` 加 `memory: Memory \| None = None` DI / `_build_chat_prompt` 变 async + prepend memory block / `run()` await / 失败隔离;1 个新 L0 test;7 个 sync→async 既有 test 修正 | `db521e0` |
| 5 | L1 e2e `test_chat_planner_self_managed_e2e.py` — happy path + memory=None + DB error 隔离 + 空 blocks placeholder | `49a4f55` |
| 6 | `chat.py` router `_build_graph_singleton` 实例化 `ChatPlanner` 时传 `memory=memory`;3 L0 DI guard test | `64c636e` |

**测试覆盖:**
- L0 unit: 24+ 新测试 + 7 既有 test sync→async 修正(`test_chat_planner_routing_prompt.py`)
- L1 integration: 4 e2e(`test_chat_planner_self_managed_e2e.py`)
- Phase 1 scope 完整 sweep: 601 PASS / 0 FAIL
- Wider sweep(整个 backend tests/): 1549 PASS / 23 SKIP / 2 FAIL(`test_orchestration_nodes.py` 2 case pre-existing 失败,跟 Phase 1 无关 — `ToolResultCache` 异步 session factory + `responder` mock prompt)
- mypy strict 全绿 / ruff 全绿

**Self-managed 三要素状态(全 wire complete):**

| 要素 | 状态 | 文件 |
|---|---|---|
| 1. Tools (可调的 MCP API) | ✅ ship(c5 Plan 4) | `mcp_server/tools/memory/` 6 文件 |
| 2. Behavior guide(教 agent 何时调) | ✅ ship + Phase 1 加金融 domain triggers | `agents/chat/prompts/memory_tool_usage.md` |
| 3. Agent loop(prompt 拼回主 prompt) | ✅ **Phase 1 接通** | `chat_planner._build_chat_prompt` + `chat_router._build_graph_singleton` |

**Phase 2-4 留 hook(看 Phase 1 dogfood feedback 后 plan):**

| Phase | 范围 | 触发条件 |
|---|---|---|
| Phase 2 | 画像层独立 PG 表 + 从 archival 图迁出"长期身份"类 edge + onboarding 表单 + UUID validation 收紧 | Phase 1 dogfood ≥ 1 周后,看 self-managed 写入分布 |
| Phase 3 | 持仓层独立 PG 表 + 接 v1.0 监控引擎 hook + 起手快照渲染 | 同上 + 跟 v1.0 portfolio 表 schema 对齐方案敲定 |
| Phase 4 | 便签层 PG `chat_scratchpad` 表 + session_id 绑定持久化 + session_end_extractor + 冷冻 30 天 Celery beat | Phase 1 ship 后立即可启 |

**Carry-over debts(reviewer 标注,留 Phase 2/4):**
- P1 — UUID validation: `ChatRequest.session_id: str`(不是 typed UUID),malformed UUID 进 planner 被 try/except 静默 fallback;`chat.py` 匿名用户 `"anonymous"` 不是 UUID,导致 anonymous 用户从不享受 memory injection。Phase 2 hardening:router 层用 typed UUID 字段 + 400 fail-fast / 给 anonymous 用户指定确定性 UUID
- P2 — `render_scratchpad_markdown` 签名是 `(memory, user_id)`,Phase 4 加 session 绑定时变 `(memory, session_id)`(`prompt_loader.py:43` 已 `noqa: ARG001` 标 session_id 待用)
- P3 — `chat_planner._build_chat_prompt` 的 `except Exception` 范围过宽,UUID 错 / 模板找不到 / 编程 bug 都被吞掉变 WARN log。Phase 2 收窄到具体 exception class
- P4 — 2 个 pre-existing test failure(`test_orchestration_nodes.py` 的 `tool_node` 和 `responder_node`)预先存在,本 Plan 不修

**简历叙事(可直接抄):**

> "继 c5 cross-session memory ship 后,撞实 spec → impl gap: working_blocks 持久化机制完备但 prompt 没真正拼回 planner,agent 看不到自己的长期记忆指令,self-managed 范式名存实亡。
>
> Plan 1 把 LLM-self-managed memory 三要素的最后一步接通 — Tools(c5 6 MCP)+ Behavior guide(memory_tool_usage.md)+ Agent loop(本 Plan)。参考 Claude Code / openclaw / Hermes 三家工业实例的共识 — 都不用'每轮批处理 extract',全部 LLM-self-managed,跟 MemGPT (Letta 2023) 哲学一致。
>
> 借 Hermes 风的 frozen snapshot 模式静态区(画像 + 便签快照,session 起手装一次)+ 动态区(c5 已 ship 的 3-way hybrid 召回)分离,prefix cache 友好。在 memory_tool_usage.md 加 3 条金融 domain triggers(投资偏好 / 加减仓 / 表态)+ 4 条 Don't save 反例,避免 agent over-writing。
>
> 6 Task / 7 commit / 24+ 新测试 / Phase 1 scope 601 PASS / 0 FAIL / mypy strict + ruff 全绿 / 失败隔离三层兜底(render.py + prompt_loader.py + chat_planner.py 各自 try/except 不让 chat 因 memory 挂掉而崩)。Phase 2-4 留 hook 等 dogfood feedback 后渐进演进。"
