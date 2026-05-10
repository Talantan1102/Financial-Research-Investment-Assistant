---
name: c5-plan4-mcp-tools-done
description: C.5 Plan 4 — 6 MCP tools + memory profile + evidence_quote 校验 ship
type: project
---

C.5 Plan 4 (6 MCP tools + memory profile + evidence_quote 校验) ship — 2026-05-11.

## ship 范围

- **6 memory MCP tools** (`backend/app/mcp_server/tools/memory/`):
  - Tier 1 写: `core_memory_append` (max 200 chars + auto-paging), `core_memory_replace` (exact substring match)
  - Tier 2 写: `archival_memory_insert` — 含 evidence_quote 校验, 调用 `HierarchicalMemory.archival_memory_insert` Plan 2A pipeline
  - Tier 2 读: `archival_memory_search` (k≤20, wraps Plan 3 3-way hybrid + RRF v2), `archival_memory_traverse` (hops≤3, wraps Plan 3 graph_traverse + 附录 D trigger words)
  - Tier 3 读: `recall_memory_search` (k≤20, in-memory cosine over qwen-embedded `chat_messages`)

- **Memory MCP profile**: `python -m app.mcp_server.server --profile memory`
  - `app.mcp_server.server.build_server(profile=...)` 多 profile 分发
  - `mcp_servers.yaml` (repo root) 列 chat_tools / memory 两 profile
  - `MCPClient.from_subprocess(profile=...)` accepts profile kwarg (default `chat_tools` 兼容 PR #39)

- **evidence_quote 强制校验** (algorithm 深度补丁 #2 part b):
  - `app.memory.injection_classifier.evidence_quote_in_episode` minimal 实现 (whitespace-tolerant substring; per shared contract § 17 A6)
  - `EvidenceNotFoundError` 继承 `ValueError`
  - `archival_memory_insert` MCP tool `handle()` 强制调; 失败 raise + 不写 edge
  - L1 双向测试 (pass / fail) + log 写入两侧验证

- **Tier 3 recall** (`backend/app/memory/recall_search.py`):
  - `RecallSearcher` class: in-memory cosine, last 5000 messages cap / user
  - 实现 Plan 1 留的 stub `HierarchicalMemory.recall_memory_search`
  - 用 raw SQL select chat_messages explicit columns 避免 ORM schema drift

- **HierarchicalMemory.archival_memory_traverse**: Plan 1 stub 替换为 wrapping `retriever.graph_traverse`; AGE 不可用时返空 list (spec § 5 fail-safe)

- **mcp_tool_call_log 表** (`app.services.trace_models.MCPToolCallLog`):
  - SQLAlchemy model + SQL migration `2026-05-11-c5-plan4-mcp-tool-call-log.sql`
  - lifespan + L1 conftest 都 apply
  - sqlite-override-friendly variants (`PgUUID(as_uuid=True).with_variant(String(36), "sqlite")`)
  - 每次 tool 调用 `_common.write_tool_call_log` 落一行 (success path: error=None; failure path: error 含 exception name)

- **System prompt 模板** (`backend/app/agents/chat/prompts/memory_tool_usage.md`):
  - 3-tier 段落 + 11 traverse trigger words + 5 hygiene rules
  - `{{persona_block}}` / `{{scratchpad_block}}` placeholders runtime fill
  - evidence_quote 约束在 agent-facing 文档明示

- **Tool routing 监控**:
  - `backend/scripts/memory/weekly_tool_routing_report.sql` — per-tool calls/hit_rate/p50/p95/error_count + per-user breakdown + per-day trend
  - `backend/eval/memory/routing_accuracy_metric.py` — `compute_routing_accuracy` skeleton (Plan 8 fills 50 case)

- **测试覆盖**:
  - L0 单测 (5 文件, 38 tests): MCP tool input schema / mcp_tool_call_log model / recall_search cosine / system prompt template / routing metric / evidence_quote / mcp_server profiles
  - L1 e2e (`test_mcp_tools_e2e.py`): 9 tests 6 tool 全跑 + evidence_quote pass/fail + log success/error 双向
  - L1 e2e (`test_recall_search.py`): 3 tests cosine + user isolation + empty corpus
  - L2 cassette (2 文件): `test_traverse_full_path.py` (PG seed → traverse handle 端到端 contract shape) + `test_recall_full_path.py` (vcr.py mark, cassette 缺失 fallback mock embed)

## 关键决策 (实施期撞实)

### 1. evidence_quote_in_episode minimal version per § 17 A6
Plan 文件原写 "如果 Plan 5 ship 在前则跳过本 task". 实施时 Plan 5 未 ship,本 Plan ship minimal 实现. **空白容忍**: `re.sub(r"\s+", "", text)` 后再 substring 比较, "买了 500 股" matches "买了500股". Plan 5 后续 Edit (NOT replace) 同文件加 `is_prompt_injection`,`evidence_quote_in_episode` 不动.

### 2. MCPToolCallLog 加在 trace_models.py 而非新文件
Plan 文件指 `app.services.trace_models` 加 model. trace_models.py 原本只有 Pydantic Span/TraceTree, 加 SQLAlchemy import 后两类 model 共存. user_id 用 `String(64)` 不用 `PgUUID` — 兼容 PR #39 trace 的 legacy str 习惯, 周报 SQL 简化.

### 3. recall_memory_search in-memory cosine, 不另建 Milvus collection
个人 portfolio 量级 (单数 user) 5000 message 上限 in-memory cosine 足够. `RecallSearcher._fetch_user_messages` 用 raw SQL explicit column list 避免 chat_messages ORM schema drift (test PG carries older schema 缺 `message_type`/`tool_call_data` 等新列). 性能撞实再升级 Milvus collection (contracts § 11 矩阵留口子).

### 4. infer_entity_types 桥接 MCP tool shorthand → HierarchicalMemory full content
spec § 6 / 附录 C tool input schema 是 shorthand: agent passes only `rel_type / source_label / target_label`. 但 `archival_memory_insert` 内部 8-step pipeline 需要 `source_entity_type / target_entity_type`. 加 `_common.infer_entity_types`: HOLDS/SOLD → User-Stock, BELONGS_TO → Stock-Industry, COMPARED/CORRELATED_WITH → Stock-Stock 等. Agent 可在 `content.source_entity_type` 显式 override.

### 5. valid_from 默认 now 不 default in Pydantic
Pydantic Literal[0.9, 0.5, 0.2] importance + UUID validate + content keys check 都在 schema 层. valid_from 在 handle() 内填 (允许 ISO override) 因为 Pydantic default factory call time != tool call time, 用 default factory 会在 schema build 时一次性绑定.

### 6. profile-aware MCPClient.from_subprocess (默认兼容 PR #39)
`from_subprocess(profile='chat_tools')` default; PR #39 既有调用 `MCPClient.from_subprocess()` 不需改. Plan 6 supervisor 引 memory tool 时显式 `profile='memory'` 启动第 2 个 subprocess.

### 7. test_mcp_tools_e2e patched_session_local + patched_memory_factory 双 fixture
- monkeypatch `app.core.database.SessionLocal` → 测试 PG sessionmaker (让 `_common.build_db_session` + `write_tool_call_log` 都走测试 PG)
- monkeypatch `_common.build_memory_from_env` → HierarchicalMemory 注入 mock LLM judge / mock embed / no-op AGE — 避免环境依赖 (DASHSCOPE_API_KEY 缺失 + pymilvus 引入)
- 这两个 fixture 是其他 Plan 后续 MCP tool e2e 测试的复用模板

### 8. L2 cassette test 默认 fallback mock 嵌入
`test_recall_full_path.py` 在 cassette 缺 + `VCR_RECORD_MODE=none` 时 fallback mock embed,不 skip — 跨 fresh checkout 也保持绿. Plan 8 dogfood 跑 `VCR_RECORD_MODE=once` 录真 cassette. (Pattern 沿用 Plan 2B `test_path_b_cross_turn_cassette` 但稍变 — Plan 2B 选 skip,Plan 4 选 fallback,因为 recall 路径轻 mock 也能 assert 路径 contract.)

## 跟 spec 决策对齐

- spec § 6 "core_memory_append max 200 chars" → Pydantic `max_length=200` ✓
- spec § 6 "importance 三档 0.9/0.5/0.2" → Pydantic `Literal[0.9, 0.5, 0.2]` ✓
- spec § 6 "k 默认 5 max 20" → Pydantic `Field(default=5, ge=1, le=20)` ✓
- spec § 6 "hops 默认 2 max 3" → Pydantic `Field(default=2, ge=1, le=3)` ✓
- spec § 6 "所有 tool 返回带 source_episode_id" → search/insert 含 `source_episode_id`; recall 含 `session_id+message_id`; traverse paths preserve AGE row dicts ✓
- spec § 11 末尾 #2 evidence_quote substring 校验 → `archival_memory_insert.handle` 强制调用, 失败 raise EvidenceNotFoundError ✓
- spec § 6 system prompt 模板 → `memory_tool_usage.md` 含 3 tier / trigger words / hygiene rules ✓
- spec § 6 监控 SQL → `weekly_tool_routing_report.sql` ship ✓
- spec § 6 eval framework → `routing_accuracy_metric.py` skeleton (Plan 8 fill 50 case) ✓

## 不在范围 (Plan 5/6/7/8 后续)

- `is_prompt_injection` 完整规则 + ML 分类器 → Plan 5 (Edit injection_classifier.py)
- Memory vs KB supervisor router → Plan 6
- /memory page 调用 weekly SQL 可视化 → Plan 7
- 50 routing accuracy golden case + 阈值 assert → Plan 8

## 关键文件 ref

- `backend/app/mcp_server/tools/memory/__init__.py` — `MEMORY_TOOL_MODULES`
- `backend/app/mcp_server/tools/memory/_common.py` — factory + log writer + Timer + `infer_entity_types`
- `backend/app/mcp_server/tools/memory/archival_memory_insert.py` — 含 evidence_quote 校验 (algorithm 深度补丁 #2)
- `backend/app/mcp_server/server.py` — `build_server(profile=...)` 多 profile 分发
- `backend/app/services/mcp_client.py` — `from_subprocess(profile=...)` (PR #39 兼容默认)
- `backend/app/memory/recall_search.py` — Tier 3 `RecallSearcher`
- `backend/app/memory/injection_classifier.py` — `evidence_quote_in_episode` + `EvidenceNotFoundError` (Plan 5 后续 Edit 加 is_prompt_injection)
- `backend/app/services/trace_models.py` — `MCPToolCallLog` 表
- `backend/app/agents/chat/prompts/memory_tool_usage.md` — system prompt 模板
- `mcp_servers.yaml` — 仓库根 MCP profile 配置
- `backend/scripts/memory/weekly_tool_routing_report.sql` — 监控周报 SQL
- `backend/eval/memory/routing_accuracy_metric.py` — Plan 8 用骨架
- `backend/scripts/migrations/2026-05-11-c5-plan4-mcp-tool-call-log.sql` — log 表 migration
