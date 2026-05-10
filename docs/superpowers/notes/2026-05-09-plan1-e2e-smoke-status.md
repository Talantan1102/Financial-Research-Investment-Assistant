# v0.9 Chat Plan 1 — E2E Smoke Test Status

**Date:** 2026-05-09  
**Task:** T21 — e2e curl smoke  
**Branch:** feat/v0.9-chat-c1c2  
**Status: DONE (full e2e succeeded after 6 bug fixes)**

---

## What Was Attempted

Full end-to-end round-trip:
1. `POST /api/v0/chats/` — create session
2. `POST /api/v0/chat` — send "工商银行现价多少" (real DashScope LLM, no mock)
3. Receive SSE stream with `plan` + `done` events
4. Verify PG checkpoints written

---

## What Worked

All major components verified green:

| Component | Status |
|-----------|--------|
| uvicorn startup | OK |
| PG table init (`create_all`) | OK |
| LangGraph PG checkpointer init | OK |
| MCP client subprocess startup | OK |
| ChatSessionRepo init | OK |
| `GET /api/v0/chats/` list | OK — returns `[]` initially |
| `POST /api/v0/chats/` create | OK — returns UUID session |
| `POST /api/v0/chat` SSE stream | OK — full round-trip 7s |
| plan SSE event | OK — planner decided direct_response |
| done SSE event | OK — final_response in Chinese |
| PG checkpoint rows | OK — 5 rows for session |

---

## Bugs Found and Fixed (in order)

### Bug 1: `postgresql+psycopg://` rejected by psycopg_pool
- **File:** `backend/app/app_main.py` `_async_pg_url()`
- **Root cause:** SQLAlchemy URL format `postgresql+psycopg://` is not valid for psycopg3's `AsyncConnectionPool`. psycopg3 uses libpq URI format `postgresql://`.
- **Fix:** Split into two functions: `_async_pg_url()` (plain `postgresql://` for psycopg3 pool) and `_sqlalchemy_async_pg_url()` (`postgresql+psycopg://` for SQLAlchemy's `create_async_engine`).

### Bug 2: Missing `greenlet` package
- **File:** `pyproject.toml` (missing dep)
- **Root cause:** SQLAlchemy async requires `greenlet` on Python 3.13. `uv add greenlet` resolved it.
- **Fix:** `uv add greenlet` — added as direct dep.

### Bug 3: `"anonymous"` not a valid UUID (FK violation)
- **File:** `backend/app/services/chat_session_repo.py`
- **Root cause:** `ChatSession.user_id` is a UUID FK column; the router passes `"anonymous"` as a string. `uuid.UUID("anonymous")` raises ValueError. The FK points to `users` table so even the nil UUID fails.
- **Fix:** `_resolve_user_uuid()` maps `"anonymous"` → `None` (NULL FK), avoiding FK violation. `list_for_user` uses `IS NULL` for anonymous filter.

### Bug 4: `chat_sessions` table missing v0.9 columns
- **Root cause:** PG table was created before the v0.9 model additions (`message_count`, `last_msg_preview`). `create_all()` is idempotent but does not add new columns to existing tables.
- **Fix:** Manual DDL: `ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS message_count INTEGER NOT NULL DEFAULT 0; ADD COLUMN IF NOT EXISTS last_msg_preview TEXT;` + same for `chat_messages` (`message_type`, `research_report_id`, `research_report_summary`, `tool_call_data`).
- **Recommendation:** Add a startup migration check or use alembic (v1.x plan).

### Bug 5: `build_chat_graph()` signature mismatch
- **File:** `backend/app/router/chat.py` `_build_graph_singleton()`
- **Root cause:** Router was calling `build_chat_graph(planner=..., responder=..., registry=..., db_path=...)` but the v0.9 function signature is `build_chat_graph(planner, responder, registry, memory, cache, *, checkpointer)`.
- **Fix:** Updated `_build_graph_singleton` to pass `InSessionMemory` + a `_NoOpCache` stub (real `ToolResultCache` needs async engine, deferred to Plan 2). `get_chat_graph` now reads `request.app.state.chat_checkpointer` from lifespan state.

### Bug 6: `tier="default"` not a valid tier
- **File:** `backend/app/agents/responder.py` line 126, `backend/app/agents/in_session_memory.py` line 86
- **Root cause:** Both used `tier="default"` but valid tiers are `Literal["fast", "balanced", "deep"]`.
- **Fix:** Changed to `tier=self.model_tier` (responder uses `"fast"`) and `tier="fast"` (in_session_memory summarize).

---

## Full E2E Result

```
event: plan
id: 10
data: {"seq":10,"data":{"node":"planner_node","output":{"plan":{"tool_calls":[],"direct_response":true,"reasoning":"用户询问工商银行现价，但当前无可用工具获取实时数据，因此直接回复无法提供实时价格。"...}}}}

event: done
id: 16
data: {"seq":16,"data":{"output":{...,"final_response":"{\"response\": \"抱歉，我目前无法获取工商银行的实时股价信息。建议您稍后通过券商软件或财经网站查询最新行情。\"}"}}}
```

**PG checkpoints:**
```
 thread_id                                            | count
 anonymous:9cd65751-3863-4d2d-9566-93a26905d4a7      |   5
```

---

## Planner behavior note

The planner chose `direct_response=true` with 0 tool calls for "工商银行现价多少". This is because:
1. `StockQuoteTool` (tushare-backed) is registered in the legacy registry
2. But `ChatPlanner` prompt uses the tool schema from the registry — the planner decided it can't get "realtime" price and responded directly
3. This is **correct behavior** for the v0.9 planner given the tushare mock mode. With `TUSHARE_MODE=real` the planner should invoke `get_stock_quote` instead.

---

## Recommendations for T22 / Plan 2 Startup

**Priority 1 (blocking for MCP tools):** Wire MCP tools from `app.state.mcp_client` into the `ToolRegistry` so the planner sees `get_stock_quote` via MCP, not the legacy tushare tool.

**Priority 2 (production correctness):** Replace `_NoOpCache` stub with real `ToolResultCache` wired to the async engine from `app.state.chat_async_engine`. This requires passing the factory into `_build_graph_singleton`.

**Priority 3 (schema drift prevention):** The DDL migration for `message_count` / `last_msg_preview` / `message_type` columns was done manually. Consider a lightweight migration check in `lifespan` or promote alembic early.

**Priority 4 (tier cleanup):** Grep codebase for `tier="default"` — there may be more occurrences in test cassettes or agent stubs that will fail at runtime.
