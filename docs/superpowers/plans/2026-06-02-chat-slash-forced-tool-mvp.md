# Chat Slash Forced-Tool MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a chat user type a slash command (e.g. `/quote 600519.SH`) to force one MCP tool to run directly, bypassing the LLM planner, and render the result via the existing `ToolCallCard`.

**Architecture:** Frontend overlays a headless **cmdk** autocomplete menu on the existing chat `<textarea>`. On send, the input is parsed: a recognized `/<alias> <arg>` becomes `forced_tool_name` + `forced_tool_args` in the existing `POST /api/v0/chat` body. Backend stores these on `ChatState`; a guard at the top of `planner_node` builds a `Plan` directly (no LLM call) so the existing `_route_after_planner → tool_node → responder_node` path runs and emits the existing `tool_start/tool_end/tool_error` SSE events. A new `GET /api/v0/tools` endpoint surfaces MCP tool metadata to drive the menu.

**Tech Stack:** Backend — FastAPI + LangGraph + Pydantic, pytest (markers `unit`/`integration`). Frontend — React 19 + valtio + Vite + cmdk + vitest/testing-library.

**Scope (this plan = spec PR-1 + PR-2):** Inline single-required-param tools only: `/quote` (`get_stock_quote`/`ts_code`), `/kb` (`kb_search`/`query`), `/web` (`web_search`/`query`). Plus `/tools` (the menu itself). **Deferred to a follow-up plan:** `get_financial_statements`, `get_market_indicators`, `get_corporate_actions` (each needs a 2nd required enum arg → modal), `compare_stocks` (list arg → modal), and all system/session commands (`/model`, `/resume`, `/branch`, `/export`) + bubble ops (retry/edit).

**Verified ground truth (file:line):**
- `ChatRequest`: `backend/app/router/chat.py:112-116` (fields: session_id, message, enable_web_search, enable_kb_search).
- Initial state + thread config: `backend/app/router/chat.py:452-461`; astream_events `:477`.
- `ChatState`: `backend/app/agents/schemas.py:210-298`. `Plan`: `:134-175`. `ToolCall`: `:105-111`.
- `planner_node`: `backend/app/orchestration/nodes.py:45-57`. `tool_node` dispatch + `args_schema.model_validate`: `:100-131`, `:249`.
- Routing `_route_after_planner`: `backend/app/orchestration/chat_graph.py:62-77`. Production graph does NOT enable `memory_kb_router` (singleton `:283-290` omits it) → planner_node is the only LLM-planning node.
- Registry/MCP: `mcp_client.list_tools()` returns `[{name, description, inputSchema}]` (`backend/app/services/mcp_client.py:59-68`). `app.state.mcp_client` set in lifespan (`backend/app/app_main.py:213`).
- Real MCP tool names: `get_stock_quote`, `get_financial_statements`, `get_market_indicators`, `get_corporate_actions`, `get_news`, `web_search`, `kb_search`, `compare_stocks`.
- Frontend: `InputArea.tsx` (textarea + `send()` + `onKey` IME guard); `ChatPane.tsx:61-67` `onSend → sse.sendMessage(text)`; `useChatSSE.ts:231-236` POST body `{session_id, message}`; dev server port `5183` proxies `/api`→`localhost:8000` (`vite.config.ts`). No cmdk yet. vitest + testing-library set up; `frontend/src/components/chat/__tests__/InputArea.test.tsx` exists.
- Test infra: `pyproject.toml:311-324` markers; run via `.venv/Scripts/python.exe -m pytest ...`. GET-endpoint test pattern: `backend/tests/integration/test_chats_router.py` (minimal app + `dependency_overrides`). SSE assertion helper: `backend/tests/integration/test_chat_router_sse.py` (`_build_test_graph`, `_collect_sse_events`). Forced path skips LLM → `LLM_MODE=mock`, no cassette.

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `backend/app/router/chat.py` | `ChatRequest` +2 fields; `GET /api/v0/tools`; pass forced fields into initial state | Modify |
| `backend/app/agents/schemas.py` | `ChatState` +2 forced fields | Modify |
| `backend/app/orchestration/nodes.py` | `planner_node` forced guard builds `Plan` directly | Modify |
| `backend/tests/integration/test_tools_endpoint.py` | `GET /api/v0/tools` test | Create |
| `backend/tests/unit/test_forced_tool_planner.py` | `planner_node` forced-guard unit test | Create |
| `backend/tests/integration/test_forced_tool_sse.py` | POST /chat forced → tool_start/tool_end SSE | Create |
| `frontend/src/components/chat/slashCommands.ts` | static alias→tool map + parse-on-send helper | Create |
| `frontend/src/api/toolsApi.ts` | `GET /api/v0/tools` client | Create |
| `frontend/src/components/chat/SlashCommandMenu.tsx` | cmdk popover menu | Create |
| `frontend/src/components/chat/InputArea.tsx` | `/` trigger detection, key mux, parse-on-send → `onSend` extended | Modify |
| `frontend/src/components/chat/ChatPane.tsx` | thread forced tool into `sse.sendMessage` | Modify |
| `frontend/src/hooks/useChatSSE.ts` | `sendMessage` accepts + sends `forced_tool_name`/`forced_tool_args` | Modify |
| `frontend/src/types/chat.ts` | `SendChatMessageRequest` +2 optional fields | Modify |
| `frontend/src/components/chat/__tests__/*` | vitest for slashCommands + menu + InputArea | Create/Modify |

---

## Task 1: Backend — `GET /api/v0/tools` endpoint

**Files:**
- Modify: `backend/app/router/chat.py` (add route near other `@router` defs, after line ~915)
- Test: `backend/tests/integration/test_tools_endpoint.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integration/test_tools_endpoint.py
import pytest
from types import SimpleNamespace
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.router.chat import router

pytestmark = pytest.mark.integration


class _StubMCP:
    async def list_tools(self):
        return [
            {"name": "get_stock_quote", "description": "quote", "inputSchema": {"type": "object", "required": ["ts_code"]}},
            {"name": "kb_search", "description": "kb", "inputSchema": {"type": "object", "required": ["query"]}},
        ]


def _client_with_mcp(mcp) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.state.mcp_client = mcp
    return TestClient(app)


def test_list_tools_returns_mcp_metadata() -> None:
    client = _client_with_mcp(_StubMCP())
    r = client.get("/api/v0/tools")
    assert r.status_code == 200
    body = r.json()
    names = [t["name"] for t in body["tools"]]
    assert names == ["get_stock_quote", "kb_search"]
    assert body["tools"][0]["inputSchema"]["required"] == ["ts_code"]


def test_list_tools_503_when_mcp_missing() -> None:
    app = FastAPI()
    app.include_router(router)
    app.state.mcp_client = None
    r = TestClient(app).get("/api/v0/tools")
    assert r.status_code == 503
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/integration/test_tools_endpoint.py -v`
Expected: FAIL — 404 (route not defined yet).

- [ ] **Step 3: Add the endpoint**

In `backend/app/router/chat.py`, after the existing `chat_retry` endpoint (~line 999), add:

```python
@router.get("/api/v0/tools")
async def list_chat_tools(request: Request) -> dict[str, Any]:
    """List MCP chat-profile tools (name/description/inputSchema) for the slash menu.

    Source of truth = the live MCP client's list_tools(); the 8 chat tools wired
    to the chat agent. Returns 503 if the MCP subprocess isn't up.
    """
    mcp_client = getattr(request.app.state, "mcp_client", None)
    if mcp_client is None:
        raise HTTPException(status_code=503, detail="tools unavailable — mcp_client not initialized")
    tools = await mcp_client.list_tools()
    return {
        "tools": [
            {
                "name": t["name"],
                "description": t.get("description", ""),
                "inputSchema": t.get("inputSchema", {}),
            }
            for t in tools
        ]
    }
```

(`Request`, `HTTPException`, `Any` are already imported in this module.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/integration/test_tools_endpoint.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/router/chat.py backend/tests/integration/test_tools_endpoint.py
git commit -m "feat(chat): GET /api/v0/tools endpoint for slash menu"
```

---

## Task 2: Backend — forced-tool fields on `ChatRequest` + `ChatState`

**Files:**
- Modify: `backend/app/router/chat.py:112-116` (`ChatRequest`)
- Modify: `backend/app/agents/schemas.py:230-232` (`ChatState`, after the v0 placeholders block)
- Test: `backend/tests/unit/test_forced_tool_planner.py` (create — will be extended in Task 3)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_forced_tool_planner.py
import pytest
from app.agents.schemas import ChatState

pytestmark = pytest.mark.unit


def test_chatstate_accepts_forced_tool_fields() -> None:
    s = ChatState(
        user_id="u1", session_id="s1", user_message="/quote 600519.SH",
        request_id="r1", trace_request_id="r1",
        forced_tool_name="get_stock_quote",
        forced_tool_args={"ts_code": "600519.SH"},
    )
    assert s.forced_tool_name == "get_stock_quote"
    assert s.forced_tool_args == {"ts_code": "600519.SH"}


def test_chatstate_forced_fields_default_none() -> None:
    s = ChatState(user_id="u1", session_id="s1", user_message="hi", request_id="r1", trace_request_id="r1")
    assert s.forced_tool_name is None
    assert s.forced_tool_args is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/unit/test_forced_tool_planner.py -v`
Expected: FAIL — `ChatState` has no `forced_tool_name` (extra field forbidden / AttributeError).

- [ ] **Step 3: Add fields to `ChatState`**

In `backend/app/agents/schemas.py`, inside `ChatState`, right after the `enable_kb_search` line (`:232`):

```python
    # === forced tool (slash command escape hatch) ===
    forced_tool_name: str | None = None
    forced_tool_args: dict[str, Any] | None = None
```

- [ ] **Step 4: Add fields to `ChatRequest`**

In `backend/app/router/chat.py`, inside `ChatRequest` (`:112-116`):

```python
class ChatRequest(BaseModel):
    session_id: str  # client-generated UUID; cross-turn session identifier
    message: str
    enable_web_search: bool = False  # v0 placeholder
    enable_kb_search: bool = False  # v0 placeholder
    forced_tool_name: str | None = None  # slash command: force this MCP tool
    forced_tool_args: dict[str, Any] | None = None  # args for the forced tool
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/unit/test_forced_tool_planner.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add backend/app/agents/schemas.py backend/app/router/chat.py backend/tests/unit/test_forced_tool_planner.py
git commit -m "feat(chat): forced_tool fields on ChatRequest + ChatState"
```

---

## Task 3: Backend — `planner_node` forced guard

**Files:**
- Modify: `backend/app/orchestration/nodes.py:45-57` (`planner_node`)
- Test: `backend/tests/unit/test_forced_tool_planner.py` (extend)

- [ ] **Step 1: Write the failing test** (append to the file)

```python
import asyncio
from app.orchestration.nodes import planner_node


class _ExplodingPlanner:
    """Planner that fails if called — proves forced path never invokes the LLM planner."""
    async def run(self, state):  # noqa: ANN001
        raise AssertionError("planner.run must NOT be called on the forced path")


def test_planner_node_forced_builds_plan_without_planner() -> None:
    state = ChatState(
        user_id="u1", session_id="s1", user_message="/quote 600519.SH",
        request_id="r1", trace_request_id="r1",
        forced_tool_name="get_stock_quote", forced_tool_args={"ts_code": "600519.SH"},
    )
    out = asyncio.run(planner_node(state, planner=_ExplodingPlanner()))
    plan = out["plan"]
    assert plan.direct_response is False
    assert len(plan.tool_calls) == 1
    assert plan.tool_calls[0].tool_name == "get_stock_quote"
    assert plan.tool_calls[0].args == {"ts_code": "600519.SH"}


def test_planner_node_no_forced_delegates_to_planner() -> None:
    state = ChatState(user_id="u1", session_id="s1", user_message="hi", request_id="r1", trace_request_id="r1")

    class _Planner:
        async def run(self, s):  # noqa: ANN001
            return {"plan": "delegated"}

    out = asyncio.run(planner_node(state, planner=_Planner()))
    assert out == {"plan": "delegated"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/unit/test_forced_tool_planner.py -v`
Expected: FAIL — `_ExplodingPlanner.run` is called (AssertionError), because the guard doesn't exist yet.

- [ ] **Step 3: Add the guard**

In `backend/app/orchestration/nodes.py`, add imports near the top if not present:

```python
from app.agents.schemas import Plan, ToolCall
```

Replace the body of `planner_node` (`:57`) so it reads:

```python
async def planner_node(state: GraphState, *, planner: ChatPlanner) -> dict[str, Any]:
    """Run ChatPlanner.run, or build a forced Plan directly when forced_tool_name is set.

    Forced path (slash command): skip the LLM planner entirely and emit a single-tool
    Plan so the existing _route_after_planner → tool_node path runs unchanged.
    """
    if state.forced_tool_name:
        return {
            "plan": Plan(
                tool_calls=[
                    ToolCall(
                        tool_name=state.forced_tool_name,
                        args=state.forced_tool_args or {},
                        rationale="user-forced via slash command",
                    )
                ],
                direct_response=False,
                reasoning=f"forced tool: {state.forced_tool_name}",
                parallelizable=False,
            )
        }
    return await planner.run(state)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/unit/test_forced_tool_planner.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/orchestration/nodes.py backend/tests/unit/test_forced_tool_planner.py
git commit -m "feat(chat): planner_node forced-tool guard (skip LLM planner)"
```

---

## Task 4: Backend — wire forced fields into stream + L1 SSE e2e

**Files:**
- Modify: `backend/app/router/chat.py:452-461` (initial `GraphState`)
- Test: `backend/tests/integration/test_forced_tool_sse.py` (create)

- [ ] **Step 1: Pass forced fields into initial state**

In `backend/app/router/chat.py`, the `initial = GraphState(...)` block (`:452-461`) — add the two fields:

```python
    initial = GraphState(
        user_id=user.id,
        session_id=req.session_id,
        user_message=req.message,
        enable_web_search=req.enable_web_search,
        enable_kb_search=req.enable_kb_search,
        request_id=request_id,
        trace_request_id=request_id,
        forced_tool_name=req.forced_tool_name,
        forced_tool_args=req.forced_tool_args,
    )
```

- [ ] **Step 2: Write the failing test** — mirror `test_chat_router_sse.py`'s `_build_test_graph` + `_collect_sse_events`

```python
# backend/tests/integration/test_forced_tool_sse.py
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Reuse the proven graph-builder + SSE parser from the existing SSE test module.
from backend.tests.integration.test_chat_router_sse import (  # type: ignore
    _build_test_graph,
    _collect_sse_events,
    _build_app,  # builds minimal app w/ chat router + DI overrides
)

pytestmark = pytest.mark.integration


def test_forced_tool_emits_tool_events_without_plan_llm() -> None:
    app = _build_app(_build_test_graph())
    client = TestClient(app)
    resp = client.post(
        "/api/v0/chat",
        json={
            "session_id": "forced-1",
            "message": "/quote 600519.SH",
            "forced_tool_name": "get_stock_quote",
            "forced_tool_args": {"ts_code": "600519.SH"},
        },
        headers={"Accept": "text/event-stream"},
    )
    assert resp.status_code == 200
    events = _collect_sse_events(resp)
    types = [e["type"] for e in events]
    assert "tool_start" in types
    assert "tool_end" in types
    start = next(e for e in events if e["type"] == "tool_start")
    assert start["data"]["tool_name"] == "get_stock_quote"
```

> NOTE: open `backend/tests/integration/test_chat_router_sse.py` first and confirm the exact names of its app-builder + SSE-collector helpers. If they are named differently (e.g. the app is built inline in a fixture rather than `_build_app`), copy that fixture's body into this test instead of importing it. The stub tool registry in that module must include `get_stock_quote` (it does — `_StubQuoteTool`); if the stub tool name differs, set `forced_tool_name`/`forced_tool_args` to match the stub.

- [ ] **Step 3: Run test to verify it fails (or reveals helper names)**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/integration/test_forced_tool_sse.py -v`
Expected: FAIL — ImportError on a helper name OR assertion. Fix imports per the NOTE, then it should fail only if wiring is wrong.

- [ ] **Step 4: Make it pass**

With Step 1 wiring done and helper names corrected, re-run:
Run: `.venv/Scripts/python.exe -m pytest backend/tests/integration/test_forced_tool_sse.py -v`
Expected: PASS — forced path produces `tool_start` + `tool_end` for `get_stock_quote`.

- [ ] **Step 5: Run the backend suite to check no regressions**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/unit backend/tests/integration -m "not slow and not live_only" -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/router/chat.py backend/tests/integration/test_forced_tool_sse.py
git commit -m "feat(chat): wire forced_tool into chat stream + L1 SSE e2e"
```

---

## Task 5: Frontend — cmdk + command registry + tools API client

**Files:**
- Modify: `frontend/package.json` (add `cmdk`)
- Create: `frontend/src/components/chat/slashCommands.ts`
- Create: `frontend/src/api/toolsApi.ts`
- Modify: `frontend/src/types/chat.ts:209-212` (`SendChatMessageRequest`)
- Test: `frontend/src/components/chat/__tests__/slashCommands.test.ts` (create)

- [ ] **Step 1: Install cmdk**

```bash
cd frontend && npm install cmdk
```
Expected: `cmdk` appears in `package.json` dependencies.

- [ ] **Step 2: Write the failing test for the parser**

```typescript
// frontend/src/components/chat/__tests__/slashCommands.test.ts
import { describe, expect, it } from 'vitest'
import { SLASH_COMMANDS, parseSlashInput } from '@/components/chat/slashCommands'

describe('slashCommands', () => {
  it('exposes the MVP commands', () => {
    const aliases = SLASH_COMMANDS.map((c) => c.alias)
    expect(aliases).toContain('/quote')
    expect(aliases).toContain('/kb')
    expect(aliases).toContain('/web')
    expect(aliases).toContain('/tools')
  })

  it('parses /quote with a ts_code into a forced tool payload', () => {
    const r = parseSlashInput('/quote 600519.SH')
    expect(r).toEqual({
      kind: 'forced_tool',
      toolName: 'get_stock_quote',
      args: { ts_code: '600519.SH' },
      displayMessage: '/quote 600519.SH',
    })
  })

  it('parses /kb with a free-text query', () => {
    const r = parseSlashInput('/kb 茅台 估值')
    expect(r).toEqual({
      kind: 'forced_tool',
      toolName: 'kb_search',
      args: { query: '茅台 估值' },
      displayMessage: '/kb 茅台 估值',
    })
  })

  it('returns plain for non-slash text', () => {
    expect(parseSlashInput('hello world')).toEqual({ kind: 'plain' })
  })

  it('returns incomplete for a command with no argument', () => {
    expect(parseSlashInput('/quote')).toEqual({ kind: 'incomplete', alias: '/quote' })
  })

  it('returns plain for /tools (menu-only, not a forced tool)', () => {
    expect(parseSlashInput('/tools')).toEqual({ kind: 'menu' })
  })
})
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/chat/__tests__/slashCommands.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 4: Implement `slashCommands.ts`**

```typescript
// frontend/src/components/chat/slashCommands.ts
// MVP slash commands — inline single-required-param MCP tools only.
// (fin/indicators/actions/compare need a 2nd enum/list arg → modal, deferred.)

export interface SlashCommand {
  alias: string            // user types this, e.g. "/quote"
  toolName: string         // real MCP tool name
  paramKey: string         // single arg key fed to the tool
  label: string            // menu label
  hint: string             // argument hint shown in the menu
}

export const SLASH_COMMANDS: SlashCommand[] = [
  { alias: '/quote', toolName: 'get_stock_quote', paramKey: 'ts_code', label: '实时行情', hint: '<ts_code> 如 600519.SH' },
  { alias: '/kb', toolName: 'kb_search', paramKey: 'query', label: '知识库检索', hint: '<查询词>' },
  { alias: '/web', toolName: 'web_search', paramKey: 'query', label: '联网搜索', hint: '<查询词>' },
  { alias: '/news', toolName: 'get_news', paramKey: 'query', label: '新闻', hint: '<查询词>' },
]

// "/tools" is the menu itself, not a forced tool.
export const MENU_ALIAS = '/tools'

export type ParseResult =
  | { kind: 'plain' }
  | { kind: 'menu' }
  | { kind: 'incomplete'; alias: string }
  | { kind: 'forced_tool'; toolName: string; args: Record<string, string>; displayMessage: string }

export function parseSlashInput(raw: string): ParseResult {
  const text = raw.trim()
  if (!text.startsWith('/')) return { kind: 'plain' }
  if (text === MENU_ALIAS) return { kind: 'menu' }

  const spaceIdx = text.indexOf(' ')
  const alias = (spaceIdx === -1 ? text : text.slice(0, spaceIdx)).toLowerCase()
  const cmd = SLASH_COMMANDS.find((c) => c.alias === alias)
  if (!cmd) return { kind: 'plain' } // unknown slash → treat as normal text

  const arg = spaceIdx === -1 ? '' : text.slice(spaceIdx + 1).trim()
  if (!arg) return { kind: 'incomplete', alias }

  return {
    kind: 'forced_tool',
    toolName: cmd.toolName,
    args: { [cmd.paramKey]: arg },
    displayMessage: text,
  }
}
```

> NOTE: `get_news`'s argument key may not be `query` (it has no required params). Before relying on `/news`, confirm its `inputSchema.properties` via `GET /api/v0/tools` and set `paramKey` accordingly; if it has no free-text property, drop `/news` from `SLASH_COMMANDS` in this plan and leave it for the modal follow-up.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/chat/__tests__/slashCommands.test.ts`
Expected: PASS.

- [ ] **Step 6: Implement `toolsApi.ts` + extend request type**

```typescript
// frontend/src/api/toolsApi.ts
const API_BASE = (import.meta.env.VITE_API_BASE as string) ?? ''

export interface ToolMeta {
  name: string
  description: string
  inputSchema: Record<string, unknown>
}

export async function fetchTools(): Promise<ToolMeta[]> {
  const base = (API_BASE ?? '').replace(/\/$/, '')
  const res = await fetch(`${base}/api/v0/tools`)
  if (!res.ok) return []
  const body = (await res.json()) as { tools: ToolMeta[] }
  return body.tools ?? []
}
```

In `frontend/src/types/chat.ts`, extend `SendChatMessageRequest` (`:209-212`):

```typescript
export interface SendChatMessageRequest {
  session_id: string
  content: string
  forced_tool_name?: string
  forced_tool_args?: Record<string, unknown>
}
```

- [ ] **Step 7: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/components/chat/slashCommands.ts frontend/src/api/toolsApi.ts frontend/src/types/chat.ts frontend/src/components/chat/__tests__/slashCommands.test.ts
git commit -m "feat(chat-fe): cmdk dep + slash command registry/parser + tools API client"
```

---

## Task 6: Frontend — `SlashCommandMenu` component

**Files:**
- Create: `frontend/src/components/chat/SlashCommandMenu.tsx`
- Test: `frontend/src/components/chat/__tests__/SlashCommandMenu.test.tsx` (create)

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/chat/__tests__/SlashCommandMenu.test.tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { SlashCommandMenu } from '@/components/chat/SlashCommandMenu'

describe('<SlashCommandMenu>', () => {
  it('renders all commands when query is just "/"', () => {
    render(<SlashCommandMenu open query="/" onSelect={vi.fn()} />)
    expect(screen.getByText('/quote')).toBeInTheDocument()
    expect(screen.getByText('/kb')).toBeInTheDocument()
  })

  it('filters by typed prefix', () => {
    render(<SlashCommandMenu open query="/qu" onSelect={vi.fn()} />)
    expect(screen.getByText('/quote')).toBeInTheDocument()
    expect(screen.queryByText('/kb')).not.toBeInTheDocument()
  })

  it('calls onSelect with the alias when an item is clicked', async () => {
    const onSelect = vi.fn()
    render(<SlashCommandMenu open query="/qu" onSelect={onSelect} />)
    await userEvent.click(screen.getByText('/quote'))
    expect(onSelect).toHaveBeenCalledWith('/quote')
  })

  it('renders nothing when open=false', () => {
    const { container } = render(<SlashCommandMenu open={false} query="/" onSelect={vi.fn()} />)
    expect(container).toBeEmptyDOMElement()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/chat/__tests__/SlashCommandMenu.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `SlashCommandMenu.tsx`**

```tsx
// frontend/src/components/chat/SlashCommandMenu.tsx
import { Command } from 'cmdk'
import { SLASH_COMMANDS } from '@/components/chat/slashCommands'
import styles from '@/styles/chat.module.scss'

export interface SlashCommandMenuProps {
  open: boolean
  query: string                 // current input value, e.g. "/qu"
  onSelect: (alias: string) => void
}

export function SlashCommandMenu(props: SlashCommandMenuProps) {
  if (!props.open) return null
  // strip leading slash for cmdk's own filtering; we pass our own filtered list anyway
  const q = props.query.replace(/^\//, '').toLowerCase()
  const items = SLASH_COMMANDS.filter((c) => c.alias.slice(1).toLowerCase().startsWith(q))
  if (items.length === 0) return null

  return (
    <div className={styles.slashMenu} role="listbox" aria-label="斜杠命令">
      <Command shouldFilter={false}>
        <Command.List>
          {items.map((c) => (
            <Command.Item key={c.alias} value={c.alias} onSelect={() => props.onSelect(c.alias)}>
              <span className={styles.slashAlias}>{c.alias}</span>
              <span className={styles.slashLabel}>{c.label}</span>
              <span className={styles.slashHint}>{c.hint}</span>
            </Command.Item>
          ))}
        </Command.List>
      </Command>
    </div>
  )
}
```

- [ ] **Step 4: Add minimal styles**

Append to `frontend/src/styles/chat.module.scss`:

```scss
.slashMenu {
  position: absolute;
  bottom: 100%;
  left: 0;
  right: 0;
  margin-bottom: 6px;
  max-height: 240px;
  overflow-y: auto;
  background: var(--surface, #fff);
  border: 1px solid var(--border, #e5e7eb);
  border-radius: 10px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
  z-index: 50;

  :global([cmdk-item]) {
    display: flex;
    gap: 10px;
    align-items: baseline;
    padding: 8px 12px;
    cursor: pointer;
    &[data-selected='true'] { background: var(--hover, #f3f4f6); }
  }
}
.slashAlias { font-family: var(--font-mono, monospace); font-weight: 600; }
.slashLabel { font-size: 13px; }
.slashHint { margin-left: auto; opacity: 0.55; font-size: 12px; }
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/chat/__tests__/SlashCommandMenu.test.tsx`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/chat/SlashCommandMenu.tsx frontend/src/components/chat/__tests__/SlashCommandMenu.test.tsx frontend/src/styles/chat.module.scss
git commit -m "feat(chat-fe): SlashCommandMenu cmdk popover"
```

---

## Task 7: Frontend — `InputArea` integration (trigger + key mux + parse-on-send)

**Files:**
- Modify: `frontend/src/components/chat/InputArea.tsx`
- Test: `frontend/src/components/chat/__tests__/InputArea.test.tsx` (extend)

- [ ] **Step 1: Write the failing tests** (append to existing `InputArea.test.tsx`)

```tsx
import { SlashCommandMenu } from '@/components/chat/SlashCommandMenu' // ensure no import error

it('shows the slash menu when input starts with "/"', async () => {
  const user = userEvent.setup()
  render(<InputArea sessionId="s1" onSend={vi.fn()} />)
  const ta = screen.getByRole('textbox')
  await user.type(ta, '/qu')
  expect(screen.getByText('/quote')).toBeInTheDocument()
})

it('selecting a command completes the textarea to "/alias "', async () => {
  const user = userEvent.setup()
  render(<InputArea sessionId="s1" onSend={vi.fn()} />)
  const ta = screen.getByRole('textbox')
  await user.type(ta, '/qu')
  await user.click(screen.getByText('/quote'))
  expect(ta).toHaveValue('/quote ')
})

it('Enter on a forced-tool input calls onSend with forced tool payload', async () => {
  const onSend = vi.fn()
  const user = userEvent.setup()
  render(<InputArea sessionId="s1" onSend={onSend} />)
  const ta = screen.getByRole('textbox')
  await user.type(ta, '/quote 600519.SH{Enter}')
  expect(onSend).toHaveBeenCalledWith('/quote 600519.SH', {
    forced_tool_name: 'get_stock_quote',
    forced_tool_args: { ts_code: '600519.SH' },
  })
})

it('Enter while menu open selects instead of sending', async () => {
  const onSend = vi.fn()
  const user = userEvent.setup()
  render(<InputArea sessionId="s1" onSend={onSend} />)
  const ta = screen.getByRole('textbox')
  await user.type(ta, '/qu{Enter}')
  expect(onSend).not.toHaveBeenCalled()
  expect(ta).toHaveValue('/quote ')
})
```

> This requires extending the `onSend` prop signature to a second optional arg. Update the existing "Enter sends message" test if it asserts arity strictly — `onSend('hello')` still holds (second arg `undefined`).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/chat/__tests__/InputArea.test.tsx`
Expected: FAIL — no slash menu rendered; `onSend` not called with payload.

- [ ] **Step 3: Modify `InputArea.tsx`**

Change the props type and wire the menu. Specific edits:

1. Update the import block to add:
```typescript
import { SlashCommandMenu } from '@/components/chat/SlashCommandMenu'
import { SLASH_COMMANDS, parseSlashInput } from '@/components/chat/slashCommands'
```

2. Change `InputAreaProps.onSend`:
```typescript
  onSend?: (
    text: string,
    forced?: { forced_tool_name: string; forced_tool_args: Record<string, unknown> },
  ) => void
```

3. Add state + derived menu visibility after `const [value, setValue] = useState('')`:
```typescript
  const [menuActiveIdx, setMenuActiveIdx] = useState(0)
  // menu opens while the input is a bare "/word" (command being typed, no space yet)
  const menuOpen = /^\/\w*$/.test(value)
  const menuItems = SLASH_COMMANDS.filter((c) =>
    c.alias.slice(1).toLowerCase().startsWith(value.replace(/^\//, '').toLowerCase()),
  )
```

4. Replace `send()` so it parses:
```typescript
  const send = useCallback(() => {
    const text = value.trim()
    if (!text) return
    const parsed = parseSlashInput(text)
    if (parsed.kind === 'forced_tool') {
      props.onSend?.(parsed.displayMessage, {
        forced_tool_name: parsed.toolName,
        forced_tool_args: parsed.args,
      })
    } else {
      props.onSend?.(text)
    }
    setValue('')
  }, [value, props])
```

5. Add a selection helper:
```typescript
  const selectCommand = useCallback((alias: string) => {
    setValue(`${alias} `)
    setMenuActiveIdx(0)
    taRef.current?.focus()
  }, [])
```

6. Replace `onKey` to mux menu navigation vs send (preserve IME guard):
```typescript
  const onKey = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.nativeEvent.isComposing) return
      if (menuOpen && menuItems.length > 0) {
        if (e.key === 'ArrowDown') {
          e.preventDefault()
          setMenuActiveIdx((i) => (i + 1) % menuItems.length)
          return
        }
        if (e.key === 'ArrowUp') {
          e.preventDefault()
          setMenuActiveIdx((i) => (i - 1 + menuItems.length) % menuItems.length)
          return
        }
        if (e.key === 'Enter' || e.key === 'Tab') {
          e.preventDefault()
          selectCommand(menuItems[menuActiveIdx].alias)
          return
        }
        if (e.key === 'Escape') {
          e.preventDefault()
          setValue('')
          return
        }
      }
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        send()
      }
    },
    [menuOpen, menuItems, menuActiveIdx, selectCommand, send],
  )
```

7. Wrap the textarea container so the menu can position absolutely, and render the menu. Find the `<div className={styles.composerInput}>` and make sure its parent (or it) is `position: relative` (the `.slashMenu` uses `bottom: 100%`). Render right above the textarea:
```tsx
        <div className={styles.composerInput} style={{ position: 'relative' }}>
          <SlashCommandMenu
            open={menuOpen && menuItems.length > 0}
            query={value}
            onSelect={selectCommand}
          />
          {/* ...existing escalate button + textarea unchanged... */}
        </div>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/chat/__tests__/InputArea.test.tsx`
Expected: PASS (existing + new).

- [ ] **Step 5: Lint + typecheck**

Run: `cd frontend && npm run lint`
Expected: no errors in the changed files.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/chat/InputArea.tsx frontend/src/components/chat/__tests__/InputArea.test.tsx
git commit -m "feat(chat-fe): slash menu trigger + key mux + parse-on-send in InputArea"
```

---

## Task 8: Frontend — thread forced tool through ChatPane + useChatSSE

**Files:**
- Modify: `frontend/src/components/chat/ChatPane.tsx:61-67`
- Modify: `frontend/src/hooks/useChatSSE.ts:197-236`
- Test: extend an existing useChatSSE test if present, else add a focused test

- [ ] **Step 1: Extend `sendMessage` signature in `useChatSSE.ts`**

Change the `sendMessage` definition (`:197`) to accept an optional forced payload and include it in the POST body (`:231-236`):

```typescript
  const sendMessage = useCallback(
    async (
      content: string,
      forced?: { forced_tool_name: string; forced_tool_args: Record<string, unknown> },
    ) => {
      // ...existing setup (appendUserMessage, beginStreaming, abort controller)...
      const res = await fetchImpl(buildChatPostUrl(), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          message: content,
          ...(forced ?? {}),
        }),
        signal: ac.signal,
      })
      // ...rest unchanged...
    },
    [/* keep existing deps */],
  )
```

> Keep every existing line in `sendMessage`; only add the `forced` param and spread `...(forced ?? {})` into the JSON body. `forced` already has snake_case keys (`forced_tool_name`/`forced_tool_args`) so it spreads directly into the request body.

- [ ] **Step 2: Pass it through `ChatPane.onSend`** (`:61-67`)

```tsx
  const onSend = useCallback(
    (
      text: string,
      forced?: { forced_tool_name: string; forced_tool_args: Record<string, unknown> },
    ) => {
      if (!sessionId) return
      void sse.sendMessage(text, forced)
    },
    [sessionId, sse],
  )
```

- [ ] **Step 3: Run frontend test suite + lint**

Run: `cd frontend && npx vitest run && npm run lint`
Expected: all pass, no lint errors in changed files.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/chat/ChatPane.tsx frontend/src/hooks/useChatSSE.ts
git commit -m "feat(chat-fe): thread forced tool from InputArea through to POST /chat body"
```

---

## Task 9: Manual browser verification (act as a user)

**Goal:** Confirm the end-to-end feature works in the real app, not just unit tests.

- [ ] **Step 1: Start backend** (needs PG/Redis/Milvus + MCP subprocess; use the project's normal run path)

Run (WSL/bash, repo root):
```bash
docker compose up -d postgres redis milvus
.venv/Scripts/python.exe -m uvicorn app.app_main:app --reload --port 8000 --app-dir backend
```
Expected: lifespan logs show MCP client up + `chat_graph` built (no "chat_graph not initialized").

- [ ] **Step 2: Start frontend**

```bash
cd frontend && npm run dev
```
Expected: Vite on `http://localhost:5183`, `/api` proxied to `:8000`.

- [ ] **Step 3: Verify `GET /api/v0/tools`**

```bash
curl -s http://localhost:8000/api/v0/tools | head -c 800
```
Expected: JSON with 8 tools incl. `get_stock_quote`, `kb_search`, `web_search`.

- [ ] **Step 4: Drive the UI in a browser (Claude-in-Chrome)** — create a new chat, then:
  1. Type `/` → assert the slash menu appears listing `/quote`, `/kb`, `/web`.
  2. Type `/qu` → assert only `/quote` shows; press Enter → textarea becomes `/quote `.
  3. Type `600519.SH` → send. Assert a `ToolCallCard` for `get_stock_quote` renders, transitions running→success, and shows a result.
  4. Confirm via console/network that the POST body included `forced_tool_name: "get_stock_quote"` and `forced_tool_args: {ts_code: "600519.SH"}`.
  5. Type `/kb 茅台` → send. Assert a `kb_search` `ToolCallCard` renders.
  6. Capture a GIF of steps 1–3 for the record.

- [ ] **Step 5: Record verification outcome** — note pass/fail per sub-step with evidence (screenshot/GIF + network payload). If any fails, debug before claiming done.

---

## Self-Review Notes (author)

- **Spec coverage:** PR-1 (Tasks 1–4) + PR-2 inline-single-param subset (Tasks 5–8) + browser verify (Task 9). Multi-param tools (`fin`/`indicators`/`actions`/`compare`), system commands, and bubble ops are explicitly deferred to follow-up plans — documented in the Scope section.
- **Forced-path semantic (spec §2.1 决策):** "调一次直接出结果" — `planner_node` builds a single-tool Plan; `responder_node` still synthesizes prose from the tool result (existing flow). The `ToolCallCard` shows the raw result regardless. This matches the determinism goal.
- **Error path:** unknown/invalid forced tool name → `tool_node._dispatch_one` → `registry.get` raises → recorded as failed `ToolResult` → existing `tool_error` SSE + retry button (spec §6.3). No new early-validation endpoint (YAGNI); the menu only offers valid tools.
- **Type consistency:** `forced_tool_name: str | None`, `forced_tool_args: dict | None` consistent across `ChatRequest`, `ChatState`, `GraphState` init, and frontend `SendChatMessageRequest`/`onSend`/`sendMessage`. `parseSlashInput` returns `displayMessage` used as the `message` field.
- **Open confirmations flagged inline:** (a) exact helper names in `test_chat_router_sse.py` (Task 4 NOTE); (b) `get_news` param key (Task 5 NOTE).
