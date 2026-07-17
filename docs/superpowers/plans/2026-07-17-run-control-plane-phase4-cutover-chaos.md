# Run Control Plane Phase 4 Cutover and Chaos Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish portable pause/resume, immutable Prompt revisions, observability, chaos acceptance, legacy data migration, and removal of the old ChatTask execution path.

**Architecture:** Pause continuation is versioned pure data and can resume on another Worker. A repeatable process harness proves failure recovery from PostgreSQL facts. Cutover occurs only after migration and parity gates, then legacy singular chat execution routes and ChatTask writers are removed in one reviewed change.

**Tech Stack:** Python/FastAPI/SQLAlchemy/PostgreSQL/Redis, Docker Compose, React/Vitest/Playwright, pytest process harness.

---

### Task 1: Versioned continuation and safe pause tools

**Files:**
- Create: `backend/app/chatloop/continuation.py`
- Modify: `backend/app/chatloop/control_tools.py`
- Modify: `backend/app/chatloop/run_executor.py`
- Modify: `backend/app/services/run_chat_worker.py`
- Test: `backend/tests/unit/chatloop/test_continuation.py`
- Test: `backend/tests/integration/test_run_pause_resume_worker.py`

- [ ] **Step 1: Write serialization/safety RED tests**

```python
payload = ContinuationV1.from_state(state, pending_action).model_dump(mode="json")
assert ContinuationV1.model_validate(payload).pending_action.tool_name == "ask_user"
assert not contains_runtime_objects(payload)
```

Reject unknown versions, connections/clients/callables, oversized payloads and non-whitelisted fields. Test approval, rejection, ask-user response, different-Worker resume, and resume not incrementing retry count.

- [ ] **Step 2: Implement `ContinuationV1` and PauseResult mapping**

Persist messages, compact tool ledger, loop count and pending action only. `approval`, `ask_user`, and pre-side-effect approval gate return typed pause directives; no Worker waits on HTTP.

- [ ] **Step 3: Integrate transactional pause/resume**

Worker calls AttemptService pause terminal command; RunService resume validates response shape by pause type. New Attempt loads resolved Pause continuation and response before executor starts.

- [ ] **Step 4: Run tests and commit**

Commit: `feat(run): resume chat from portable pause points`.

### Task 2: Revision history and frontend interaction completion

**Files:**
- Modify: `backend/app/services/run_service.py`
- Modify: `backend/app/services/run_session_service.py`
- Modify: `backend/app/schemas/run_session.py`
- Modify: `frontend/src/hooks/useRunSSE.ts`
- Modify: `frontend/src/components/chat/ChatPane.tsx`
- Test: `backend/tests/unit/services/test_run_revision_chain.py`
- Test: `frontend/src/components/chat/__tests__/ChatPane.test.tsx`

- [ ] **Step 1: Write revision RED tests**

Prove A→B→C linearity, reject C→A fork, latest revision selection, old Run immutability, authorization, and model history excluding superseded Prompt versions.

- [ ] **Step 2: Implement revision projections**

Session detail returns each Run with `replaces_run_id`, terminal/current status and final message summary, plus `latest_run_id`. No mutation of old Message/Run rows.

- [ ] **Step 3: Finish UI semantics**

Waiting UI renders approval/input forms; response calls resume. “修改后重试” sends a new Run with predecessor ID. Revision history is expandable; no steering fallback exists.

- [ ] **Step 4: Run backend/frontend tests and commit**

Commit: `feat(run): expose pause and prompt revision UX`.

### Task 3: Metrics and structured audit

**Files:**
- Create: `backend/app/services/run_metrics.py`
- Create: `backend/app/router/run_observability.py`
- Modify: `backend/app/processes/run_scheduler.py`
- Modify: `backend/app/processes/run_dispatcher.py`
- Modify: `backend/app/processes/run_worker.py`
- Test: `backend/tests/integration/test_run_metrics.py`
- Test: `backend/tests/unit/test_run_log_context.py`

- [ ] **Step 1: Write metric/log RED tests**

Assert Run counts, queue depth/oldest wait, scheduling latency/no-slot/fair allocations, Worker load/heartbeat, lease expiry, Attempt outcomes, Outbox backlog/retries, waiting counts, duration/token/cost. Capture logs and assert correlation IDs exist while prompt/key/token content is absent.

- [ ] **Step 2: Implement read-only metrics service/router**

Use aggregate PostgreSQL queries; metrics endpoint follows existing observability auth pattern and cannot mutate scheduling state.

- [ ] **Step 3: Add process log context and commit**

Commit: `feat(run): add control plane observability`.

### Task 4: Deterministic chaos harness

**Files:**
- Create: `backend/tests/chaos/run_control_harness.py`
- Create: `backend/tests/chaos/test_run_control_failures.py`
- Create: `backend/scripts/run_control_chaos.ps1`
- Modify: `docker-compose.yml`

- [ ] **Step 1: Write harness self-tests**

The harness must resolve exact Compose service/container IDs, wait on health with bounded timeout, kill/restart one named process, and query PostgreSQL evidence. It refuses destructive actions outside the run-control Compose project.

- [ ] **Step 2: Implement twelve acceptance scenarios**

Encode browser disconnect, two-Worker parallelism, Tenant fairness, dual Scheduler, duplicate notification, first/second Worker crash, cancel+crash, pause/resume slot release, revision chain, Redis restart, Scheduler/Dispatcher restart, and legacy-writer-zero checks.

- [ ] **Step 3: Run true-process chaos suite**

Each scenario records Run/Attempt/Event/Outbox rows and exact elapsed time. No scenario passes solely from logs or process presence.

- [ ] **Step 4: Commit**

Commit: `test(run): prove control plane failure recovery`.

### Task 5: Legacy data migration and cutover gate

**Files:**
- Create: `backend/app/scripts/migrate_legacy_chat_to_runs.py`
- Create: `backend/tests/integration/test_legacy_chat_migration.py`
- Create: `backend/app/scripts/verify_run_cutover.py`
- Test: `backend/tests/integration/test_run_cutover_gate.py`
- Modify: `backend/app/models/chat.py`
- Modify: `backend/app/models/research_report.py`
- Modify: `backend/app/models/user.py`
- Modify: `backend/app/router/attachment_router.py`
- Modify: `backend/app/router/escalate.py`
- Modify: `backend/app/services/research_report_repo.py`
- Modify: `backend/app/service/memory_service.py`
- Modify: `backend/app/memory/recall_search.py`
- Modify: `backend/app/chatloop/rebuild.py`
- Modify: `backend/app/tasks/chat_memory_hook.py`
- Modify: `backend/app/tasks/title_generation.py`

- [ ] **Step 1: Write migration RED tests**

Cover dry-run no writes, deterministic Session/Message mapping, ownership/tenant resolution, rerun idempotency, malformed row quarantine, source/target counts, and destructive cleanup refusing without `--confirm-drop-legacy-data`.

- [ ] **Step 2: Implement migration command**

Default mode prints JSON report only. `--apply` performs batched transactions with stable legacy-to-new mapping records. Cleanup requires prior successful report hash, explicit confirmation, and database name echo.

Migrate ChatAttachment to RunSession/RunMessage FKs, ChatSessionContext to a RunSession context row, LongTermMemory.session to RunSession, and ResearchReport source linkage to RunSession. Rewire attachment, memory, rebuild, title and research repositories before the old FK is removed. Move escalation to `/api/v1/tenants/{tenant_id}/research-escalations` with `source_run_id/source_session_id`; it is not a Run execution endpoint.

Destructive cleanup additionally requires `--backup-manifest <path>` produced by a successful `pg_dump`; validate the manifest database name, timestamp and SHA-256 before dropping legacy constraints/tables. The cutover verifier fails when this evidence is absent.

- [ ] **Step 3: Implement cutover verifier**

Fail unless migration counts match, no active ChatTask remains, frontend build references no singular chat execution URL, OpenAPI contains new Run/Session routes, and Phase 2/3 done-card gates exist.

- [ ] **Step 4: Run migration against disposable PostgreSQL and commit**

Commit: `feat(run): migrate legacy chat state for cutover`.

### Task 6: Remove legacy execution path

**Files:**
- Delete: `backend/app/router/chat.py`
- Delete: `backend/app/router/chat_finalize.py`
- Delete: `backend/app/router/chats.py`
- Delete: `backend/app/services/chat_task_repo.py`
- Delete: `backend/app/services/chat_session_repo.py`
- Delete: `backend/app/services/chat_event_bus.py`
- Delete: `backend/app/services/chat_cancel_bus.py`
- Delete: `backend/app/services/chat_steer_bus.py`
- Delete: `backend/app/tasks/chat_runner.py`
- Delete: `backend/app/tasks/chat_stale_scanner.py`
- Modify: `backend/app/models/chat.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/app_main.py`
- Modify: `backend/app/tasks/celery_app.py`
- Modify: `backend/app/tasks/celery_beat_schedule.py`
- Delete: `frontend/src/hooks/useChatSSE.ts`
- Delete: `frontend/src/hooks/__tests__/useChatSSE.test.tsx`
- Modify: `frontend/src/api/chatApi.ts`
- Modify: `frontend/src/api/__tests__/chatApi.test.ts`
- Modify: `frontend/src/types/chat.ts`
- Modify: `frontend/src/types/__tests__/chat.test.ts`
- Modify: `frontend/src/store/current-chat.ts`
- Modify: `frontend/src/store/chat-sessions.ts`
- Modify: `frontend/src/components/chat/ChatPane.tsx`
- Modify: `frontend/src/components/sidebar/chat-session-list.tsx`
- Modify: `frontend/src/pages/chat/session.tsx`
- Modify: `frontend/src/pages/chat/landing.tsx`
- Test: `backend/tests/integration/test_no_legacy_chat_execution.py`

- [ ] **Step 1: Inventory exact imports and write deletion gate RED test**

Use `rg` to list every import/URL/ChatTask write. Test fails if singular `/api/v0/chat`, ChatTask ORM/repository, steer/retry endpoint, or Celery chat task remains registered. Explicitly allow unrelated Celery tasks and reusable ToolLoop modules.

- [ ] **Step 2: Remove writers/routes in dependency order**

First switch all consumers to Run APIs, then unregister router/task, remove repos/buses, remove ChatTask class/relations, and update model imports. Do not delete `ChatLoopState`, ToolLoop, MCP, Skill, Memory, Trace, generic Redis or non-chat Celery.

- [ ] **Step 3: Run targeted and full import/OpenAPI/frontend gates**

Verify no dangling lazy imports, Celery autodiscovery errors, or old frontend URLs. Commit: `refactor(chat): retire legacy chat execution path`.

### Task 7: Final acceptance, docs, and branch review

**Files:**
- Create: `docs/claude-context/run-control-plane-phases2-4-done.md`
- Modify: `CLAUDE.md`
- Modify: `README.md`
- Modify: `docker-compose.yml`
- Modify: `frontend/README.md`

- [ ] **Step 1: Run full scoped verification**

Run Phase 1-4 unit/integration suites, Ruff format/check, mypy, frontend test/build/lint, OpenAPI exact operation checks, true Redis/PostgreSQL multi-process chaos, cassette and credential-safe live smoke. Record wider-suite environment failures separately and never label them green.

- [ ] **Step 2: Independent whole-branch review**

Review `origin/main...HEAD` for spec compliance, security/tenant isolation, transaction boundaries, zombie Worker fencing, Redis-as-truth regressions, legacy writers, data-loss risk and test evidence. Fix all Critical/Important findings and re-review.

- [ ] **Step 3: Write done card and commit**

Document exact commits, commands, counts, process topology, live smoke evidence, removed legacy surfaces, remaining Minor risks and operator commands. Commit: `docs(run): record run control plane completion`.
