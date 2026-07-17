# Run Control Plane Phase 3 Chat Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute real Chat Runs through the Phase 2 Worker, persist final facts in PostgreSQL, stream temporary tokens through Redis, and switch React to the new Run API.

**Architecture:** A transport-free ChatRunExecutor wraps the existing ToolLoop. RunChatWorkerAdapter translates executor results into AttemptService transactions; RunStreamBus carries temporary events; the existing Run Events endpoint merges durable PostgreSQL events with Redis using an opaque composite cursor.

**Tech Stack:** Python 3.12, existing ChatLoop/MCP/Skill stack, SQLAlchemy/PostgreSQL, redis.asyncio, FastAPI SSE, React/TypeScript/Vite/Vitest.

---

## File map

- `backend/app/chatloop/run_executor.py`: pure Run-oriented Chat execution adapter.
- `backend/app/services/run_chat_worker.py`: Attempt claim/execute/persist orchestration.
- `backend/app/models/run_execution.py`: tool ledger and usage ORM.
- `backend/app/services/run_stream_bus.py`: temporary Redis events and cursor primitives.
- `backend/app/router/run_sessions.py`: new Session resource read model.
- `frontend/src/api/runApi.ts`, `frontend/src/hooks/useRunSSE.ts`: new frontend transport.

### Task 1: Tool ledger, usage, and Session archive schema

**Files:**
- Create: `backend/app/models/run_execution.py`
- Modify: `backend/app/models/run.py`
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/unit/models/test_run_execution_models.py`

- [ ] **Step 1: Write failing physical-contract tests**

Pin exact tables, columns, composite FKs, `idempotency_key` uniqueness, usage non-negative checks, model/token indexes, and `run_sessions.archived_at`.

```python
def test_tool_execution_idempotency_is_global_per_run(db_session):
    assert unique_columns(db_session, "run_tool_executions", "uq_run_tool_idempotency") == (
        "run_id", "idempotency_key"
    )
```

- [ ] **Step 2: Run RED**

Run target test. Expected: missing model/table failure.

- [ ] **Step 3: Implement models**

`RunToolExecution` stores bounded request/result JSON summaries and exact statuses `started/completed/failed/approval_required`. `RunUsageRecord` stores provider/model and non-negative token/cost fields with Run/Attempt provenance. Add nullable indexed `archived_at` to RunSession.

- [ ] **Step 4: Run Task 1 plus Phase 1/2 model tests and commit**

Commit: `feat(run): persist chat execution facts`.

### Task 2: Extract transport-free ChatRunExecutor

**Files:**
- Create: `backend/app/chatloop/run_executor.py`
- Modify: `backend/app/chatloop/loop.py`
- Modify: `backend/app/chatloop/worker_wiring.py`
- Test: `backend/tests/unit/chatloop/test_run_executor.py`
- Test: `backend/tests/integration/chatloop/test_run_executor_tools.py`

- [ ] **Step 1: Write result-contract RED tests**

```python
result = await executor.execute(command)
assert isinstance(result, CompletedResult)
assert result.final_text == "answer"
assert result.usage.output_tokens > 0
```

Scripted cases cover completed, model error, tool error, cancel during token stream, input pause, approval pause, and continuation resume. Assert Executor never imports ORM, Celery, FastAPI, ChatTask repo, or Redis bus modules.

- [ ] **Step 2: Define immutable interfaces**

```python
@dataclass(frozen=True)
class ExecuteChatRun:
    run_id: UUID
    attempt_id: UUID
    session_id: UUID
    prompt: str
    history: tuple[dict[str, Any], ...]
    continuation: dict[str, Any] | None

CompletedResult | PauseResult | FailedResult
```

Event sink is an injected async callable; cancel is an injected `asyncio.Event`.

- [ ] **Step 3: Extract from old runner without changing old behavior**

Reuse ToolLoop construction and ChatLoopState projection. Keep old `run_chat_async()` tests green by adapting it to call shared execution code during the parallel-validation period.

- [ ] **Step 4: Run old and new ChatLoop suites and commit**

Commit: `refactor(chat): extract run-oriented executor`.

### Task 3: Run Chat Worker persistence adapter

**Files:**
- Create: `backend/app/services/run_chat_worker.py`
- Modify: `backend/app/services/attempt_service.py`
- Modify: `backend/app/processes/run_worker.py`
- Test: `backend/tests/unit/services/test_run_chat_worker.py`
- Test: `backend/tests/integration/test_run_chat_worker_pg.py`

- [ ] **Step 1: Write atomic-result RED tests**

Test that completed writes assistant message/final_message/Run/Attempt/Event/usage/trace atomically; injected failure before commit leaves all unchanged. Test fail/pause/cancel and zombie token rejection.

- [ ] **Step 2: Implement worker adapter**

```python
class RunChatWorker:
    async def execute_assignment(self, assignment: ClaimedAssignment) -> None:
        raise NotImplementedError
```

Load Run input/history/continuation after claim, start a lease-renew task, map Loop events through injected sinks, and call transaction-owned AttemptService terminal methods. Stop renewal before terminal commit and always close executor resources.

- [ ] **Step 3: Implement tool ledger integration**

Before a tool call, derive stable key from run/tool_call/tool/args hash. Return cached completed result; reject unsafe non-idempotent execution without approval; persist start/result through a transaction-bound ledger store.

- [ ] **Step 4: Run PostgreSQL integration and old runner regression; commit**

Commit: `feat(run): execute chat attempts durably`.

### Task 4: Redis Run stream and composite SSE cursor

**Files:**
- Create: `backend/app/services/run_stream_bus.py`
- Modify: `backend/app/router/runs.py`
- Modify: `backend/app/schemas/run.py`
- Test: `backend/tests/unit/services/test_run_stream_bus.py`
- Test: `backend/tests/integration/test_run_events_live_sse.py`

- [ ] **Step 1: Write cursor and bus RED tests**

```python
cursor = RunEventCursor.parse("v1:5:1721181123000-4")
assert cursor.durable_seq == 5
assert cursor.redis_id == "1721181123000-4"
assert RunEventCursor.parse("5").durable_seq == 5
```

Test invalid cursor 422, maxlen/TTL, Redis write degradation, durable-before-token ordering, disconnect resume without duplicate, terminal final drain, and terminal reconnect using final message without old token replay.

- [ ] **Step 2: Implement versioned bus/envelope**

Stream key `run:stream:{run_id}`; envelope contains version, run/attempt, kind, payload, durable watermark. No credentials or raw hidden reasoning are accepted event kinds.

- [ ] **Step 3: Extend SSE generator**

Drain DB after durable cursor, XREAD Redis after redis cursor while nonterminal, and repeat DB drain after bounded Redis block timeout. On terminal, final DB drain then close. Keep six Run route paths unchanged.

- [ ] **Step 4: Run tests and commit**

Commit: `feat(run): stream live run events with resumable cursors`.

### Task 5: Session resource API

**Files:**
- Create: `backend/app/services/run_session_service.py`
- Create: `backend/app/router/run_sessions.py`
- Create: `backend/app/schemas/run_session.py`
- Modify: `backend/app/app_main.py`
- Test: `backend/tests/integration/test_run_sessions_v1_router.py`

- [ ] **Step 1: Write RBAC/API RED tests**

Cover list/detail/title/archive; member own scope; owner/admin Tenant scope; outsider and another member receive 404; archived Sessions excluded by default but retrievable by direct authorized detail; archive does not delete Run history.

- [ ] **Step 2: Implement service and exact routes**

Routes:

```text
GET    /api/v1/tenants/{tenant_id}/sessions
GET    /api/v1/tenants/{tenant_id}/sessions/{session_id}
PATCH  /api/v1/tenants/{tenant_id}/sessions/{session_id}
DELETE /api/v1/tenants/{tenant_id}/sessions/{session_id}
```

No route creates or executes Run. Use async session factory and current-user dependency.

- [ ] **Step 3: Verify OpenAPI boundaries and commit**

Assert exactly six Run operations plus four Session resource operations and absence of a second execution POST. Commit: `feat(run): expose tenant session read model`.

### Task 6: React Run transport and UI semantics

**Files:**
- Create: `frontend/src/api/runApi.ts`
- Create: `frontend/src/hooks/useRunSSE.ts`
- Modify: `frontend/src/components/chat/ChatPane.tsx`
- Modify: `frontend/src/store/current-chat.ts`
- Modify: `frontend/src/store/chat-sessions.ts`
- Test: `frontend/src/api/__tests__/runApi.test.ts`
- Test: `frontend/src/hooks/__tests__/useRunSSE.test.tsx`
- Test: `frontend/src/components/chat/__tests__/ChatPane.test.tsx`

- [ ] **Step 1: Write frontend RED tests**

Test POST Run with Idempotency-Key, two-stage POST→GET events, composite Last-Event-ID reconnect, GET Run terminal calibration, cancel, resume, modified Prompt creating `replaces_run_id`, and no steer/retry calls on new path.

- [ ] **Step 2: Implement typed API and hook**

`useRunSSE` exposes `sendPrompt`, `cancelRun`, `resumeRun`, `resubmitPrompt`, `status`, and `activeRunId`. It uses fetch/ReadableStream for Authorization header and retains opaque event IDs without parsing them in UI code.

- [ ] **Step 3: Switch ChatPane and Session store**

Lazy-create Session on first Run, load sidebar from v1 Session API, render durable final message after terminal calibration, and remove steering UI behavior from the new hook.

- [ ] **Step 4: Run Vitest, TypeScript build, ESLint and commit**

Run `npm test -- --run`, `npm run build`, `npm run lint`. Commit: `feat(chat): switch frontend execution to run API`.

### Task 7: Real Chat acceptance and Phase 3 done card

**Files:**
- Create: `backend/tests/integration/test_run_chat_full_path.py`
- Create: `backend/tests/e2e/test_run_chat_cassette.py`
- Create: `backend/scripts/smoke_run_chat.py`
- Modify: `docker-compose.yml`
- Create: `docs/claude-context/run-control-plane-phase3-chat-integration-done.md`

- [ ] **Step 1: Add full-path scripted/cassette tests**

POST Run, wait for Scheduler/Dispatcher/Worker, consume SSE, and assert completed Run, final message, Attempt, usage and trace. Run two Sessions concurrently and prove distinct Worker IDs where capacity is one.

- [ ] **Step 2: Add credential-safe live smoke script**

Script reads existing model configuration, creates one Run, prints only IDs/status/timing, waits with timeout, verifies final message nonempty and trace present, and never prints API keys or full prompt.

- [ ] **Step 3: Run all Phase 3 gates**

Run backend target suites, frontend tests/build/lint, true Redis multi-process path, cassette, then one live smoke when configured. Record exact commands, counts, model route and sanitized IDs.

- [ ] **Step 4: Commit**

Commit: `feat(run): complete phase 3 chat integration`.
