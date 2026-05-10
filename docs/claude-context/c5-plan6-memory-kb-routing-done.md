---
name: c5-plan6-memory-kb-routing-done
description: C.5 Plan 6 Memory vs KB routing ship — supervisor router + 触发词分类 + prompt 区隔 + routing eval framework
type: project
---

C.5 Plan 6 (Memory vs KB Search 检索路由 — spec § 11 末尾 #7) ship — 2026-05-10.

## ship 范围

spec § 11 末尾 #7 4 个补丁要点全 cover:

- **(a) LangGraph supervisor 加 router 节点** 输出 `retrieval_targets: ["memory" | "kb" | "both"]`
  - `backend/app/orchestration/memory_kb_router_node.py`: LangGraph node wrapper + asyncio.gather 并行 + graceful degrade
  - `backend/app/orchestration/chat_graph.py`: Edit `build_chat_graph` 加 `kb_search_service` / `memory_kb_router_fn` 两个 default-None 参数(必须配对), topology 插入 `context_node → memory_kb_router_node → planner_node`
- **(b) 触发词区分**: memory / KB / both
  - `backend/app/memory/memory_kb_router.py`: `MEMORY_TRIGGER_WORDS` (13) / `KB_TRIGGER_WORDS` (11) / `BOTH_TRIGGER_PATTERNS` (6 regex)
  - 严守契约 § 8 一字不漂移; rule_match 优先级 both pattern > 双触发 > 单类 > None
- **(c) 两路结果 prompt 显式区隔** `[用户上下文]` / `[市场知识]`
  - `backend/app/agents/chat_planner.py`: Edit `_build_chat_prompt` 注入区隔段 + 显式 disclaimer ("用户偏好白马 + 市场跑输 是 trade-off, 不是矛盾")
  - top-5 hits 防爆 + 240 char chunk_text 截断
- **(d) 默认 fallback memory** (个人化场景多)
  - `LLMRouterFallback` 任何错误 fallback `["memory"]`; rule miss + 无 LLM fallback 也 fallback `["memory"]`
  - `decide_retrieval_targets()` 三层瀑布: rule → LLM → default memory

附加:
- `backend/app/agents/schemas.py` Edit ChatState 加 4 字段 (`retrieval_targets` / `memory_hits` / `kb_hits` / `memory_kb_routing_reasoning`), backward compat 默认 [] / None
- `backend/eval/memory/routing_accuracy_seed.jsonl` Plan 6 提供 8 seed case (2 memory + 2 kb + 2 both + 2 boundary)
- `backend/eval/memory/routing_accuracy_hook.py` `RoutingCase` + `compute_routing_accuracy` + `load_routing_cases` (Plan 8 用此 hook 扩到 50 case + 阈值 ≥ 0.85)

## 关键决策 (实施期撞实)

- **`LLMService.chat` 是 sync, 不是 async**: plan 文件原写 `await self._llm.chat(...)` 是错的。决议: `LLMRouterFallback.decide()` 保留 `async def` 签名做 forward-compat hook, 但内部 sync 调 `LLMService.chat()`。test 用 `_StubLLMService` (有 sync `chat()` 方法) 替换 `AsyncMock`。
- **`LLMResponse.usage` 字段不存在**: plan 文件 fixture 有误。决议: 实测 schema 是 `prompt_tokens` / `completion_tokens` / `total_tokens` 三个分立字段; test stub 用 `_FakeRawCompletion` (满足 `ChatCompletionRaw` Protocol) 而不是真 `LLMResponse`。
- **跟 PR #39 chat_router 不撞**: 现有 `app/router/chat.py::_build_graph_singleton` 不传 `kb_search_service` / `memory_kb_router_fn`, 走 backward-compat 老 topology。Plan 6 ship 不动 chat_router; Plan 7 接 KB Search 真注入(本 plan 范围外)。
- **`_build_chat_prompt` 抽 helper 路径**: plan 文件原写抽 `_render_prompt`, 但现有 ChatPlanner 已有 `_build_chat_prompt` 暴露入口, 直接 Edit 复用避免双重命名。test 调用同名方法。
- **`backend/eval/memory/` 已是 Python 包**: 实测 `__init__.py` 已存在, import path = `from eval.memory.routing_accuracy_hook import ...` (不是 plan 文件原写的 `app.eval.memory`)。文件名 `routing_accuracy_hook.py` 跟 Plan 4 已 ship 的 `routing_accuracy_metric.py` (memory MCP tool 选择, 跟 Plan 6 supervisor 路由是两层不同 routing) 区分。
- **`_StubMemory.load_for_turn` / `save_after_turn`**: Memory Protocol 要求, 在 e2e cassette test stub 必须实现(空实现即可)否则 mypy 报 missing protocol member。
- **anonymous user_id graceful**: 旧 caller 用字面量 `"anonymous"` (非 UUID), Plan 6 router_node 用 try/except 捕 `ValueError/AttributeError/TypeError` fallback `00000000-...`-UUID, 让 memory layer 自决; 不抛阻塞 graph 执行。
- **L2 cassette skip-if-absent**: 沿用 Plan 2B `test_path_b_cross_turn_cassette.py` 的 `VCR_RECORD_MODE=once` + cassette absence 检测 → `pytest.skip` 模式; fresh checkout / CI 不带 secret 默认绿。

## 跟 § 17 audit 对齐

- ✓ § 8 触发词清单一字不漂移(memory 13 / kb 11 / both 6, 全字面量在 contract test 锁死)
- ✓ § 1 文件位置: `memory_kb_router.py` 在 `backend/app/memory/`(逻辑归 memory), node wrapper 在 `backend/app/orchestration/`(编排归 orchestration)
- ✓ § 11 范围矩阵: Plan 6 在 "Memory vs KB routing(#7)" 唯一 ✓ ship; 跟 Plan 1-5 / 7-8 不冲突
- ✓ § 12 测试分层: L0(Task 1-5/7-8)+ L1(Task 6) + L2(Task 9), 无遗漏
- ✓ § 14 commit: 9 task → 9 commit, 首词全 `feat(c5-plan6)` / `test(c5-plan6)`

## 偏离 plan 决策

1. plan §3 Step 3.3 corpus 1 case 校准: "我对市场的态度" → "我对当前形势的态度"(避免 KB "市场" 触发词串入 → 实际就是 both, 不是 memory; plan 文件已预留 30 min 校准时间)
2. plan §8.2 Python module 路径: 实际 `backend/eval/memory/`(已存在 package), 不是 `backend/app/eval/memory/`; jsonl 路径相同
3. plan §1 文件 `routing_accuracy_seed.jsonl` 1 case 修正: "我对消费板块的偏好" expected 从 memory 改 both(板块 是 KB trigger word; 跟 rule_match 行为一致, 不强行规则给错答案)

## 关键文件 ref

### 实现层

- `backend/app/memory/memory_kb_router.py`: RouterDecision schema + 触发词清单 + rule_match + LLMRouterFallback + decide_retrieval_targets
- `backend/app/orchestration/memory_kb_router_node.py`: LangGraph node wrapper + asyncio.gather 并行 + graceful degrade
- `backend/app/orchestration/chat_graph.py` (Edit): build_chat_graph 加 kb_search_service / memory_kb_router_fn(可选注入)
- `backend/app/agents/chat_planner.py` (Edit): _build_chat_prompt 加 [用户上下文] / [市场知识] 段 + disclaimer
- `backend/app/agents/schemas.py` (Edit): ChatState 加 retrieval_targets / memory_hits / kb_hits / memory_kb_routing_reasoning 4 fields
- `backend/eval/memory/routing_accuracy_seed.jsonl`: 8 seed case
- `backend/eval/memory/routing_accuracy_hook.py`: RoutingCase + load_routing_cases + compute_routing_accuracy

### 测试

- L0: `tests/unit/memory/test_memory_kb_router.py` (72 cases — schema + contract + rule_match + LLMRouterFallback + decide_retrieval_targets + 30 corpus)
- L0: `tests/unit/orchestration/test_memory_kb_router_node.py` (7 cases)
- L0: `tests/unit/agents/test_chat_state_routing.py` (7 cases)
- L0: `tests/unit/agents/test_chat_planner_routing_prompt.py` (7 cases)
- L0: `tests/unit/memory/test_routing_accuracy_hook.py` (8 cases)
- L1: `tests/integration/memory/test_kb_routing_e2e.py` (6 cases — memory only / kb only / both parallel / legacy topology / 配对 ValueError ×2)
- L2: `tests/e2e/memory/test_memory_kb_routing_cassette.py` (1 case, skip 当 cassette absent + 无 API key)

累计 ~107 unit + 6 L1 + 1 L2(skipped) cases all green。

## Done criteria

- ✓ 9 task 全 ship + 每 task 立即 commit (9 commits in this plan)
- ✓ 触发词清单 § 8 contract test 锁死, 一字不漂移
- ✓ Plan 6 + 累计 c5 测试套件无退化 (chat_state / chat_planner / chat_graph 既有 tests 全过)
- ✓ ruff + mypy strict 0 error on Plan 6 source files
- ✓ backward compat: legacy chat_router 不传 kb_search_service / memory_kb_router_fn 维持老 topology
- ✓ 知识卡 + CLAUDE.md 索引 (本卡)

## Plan 8 收束

- 50 case routing accuracy golden + assert ≥ 0.85
- multi-scenario 不矛盾化 cassette(用户看空 vs 市场看多 / 偏好长期 vs 新闻看短 etc.)
- routing accuracy 周报 dashboard
- L2 cassette 录制 (作者本地 dogfood)
