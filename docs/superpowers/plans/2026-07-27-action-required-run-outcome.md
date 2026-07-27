# Action Required Run Outcome Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Represent “the chat Run completed normally but the user must perform an external action” as a durable, generic Run outcome and render it as an actionable conversation card.

**Architecture:** Keep `RunStatus.COMPLETED` unchanged and add a validated terminal outcome payload to the completed executor result and durable Run record. Transport that payload through snapshot and SSE APIs, then render a generic React card whose link only navigates and whose “continue” action creates a new user turn.

**Tech Stack:** Python dataclasses/Pydantic, SQLAlchemy/PostgreSQL, FastAPI SSE, pytest, React 19, TypeScript, Vitest, Playwright.

---

## File map

- Create `backend/app/chatloop/outcomes.py`: frozen `ActionRequiredOutcome` contract and validation.
- Modify `backend/app/chatloop/run_executor.py`: completed results can carry an optional outcome.
- Modify `backend/app/models/run.py`: durable `outcome_code` and `outcome_payload` columns.
- Modify `backend/app/services/attempt_service.py`: atomically persist outcome and publish it in `run.completed`.
- Modify `backend/app/schemas/run.py`, `backend/app/schemas/run_session.py`, `backend/app/router/runs.py`, and `backend/app/router/run_sessions.py`: expose outcome in snapshots, session reloads, and SSE.
- Modify `backend/app/scripts/migrate_phase3_execution_schema.py`: add and verify canonical columns/constraints.
- Modify `frontend/src/api/runApi.ts` and `frontend/src/hooks/useRunSSE.ts`: typed outcome transport.
- Create `frontend/src/components/chat/ActionRequiredCard.tsx`: generic user action card.
- Modify `frontend/src/components/chat/ChatPane.tsx`: render the card without treating it as a pause.

### Task 1: Define a bounded terminal outcome contract

**Files:**
- Create: `backend/app/chatloop/outcomes.py`
- Test: `backend/tests/unit/chatloop/test_outcomes.py`

- [ ] **Step 1: Write failing validation tests**

```python
def test_action_required_accepts_internal_navigation_only():
    outcome = ActionRequiredOutcome(
        action_type="apply_market_permission",
        action_url="/market-permissions/star/apply",
        action_label="申请科创板权限",
        resume_hint="申请完成后回来继续下单",
        intent_summary="买入中芯国际 100 股",
    )
    assert outcome.code == "action_required"


@pytest.mark.parametrize("url", ["https://evil.example/x", "//evil.example/x", "javascript:alert(1)"])
def test_action_required_rejects_external_or_active_urls(url):
    with pytest.raises(ValidationError):
        ActionRequiredOutcome(action_type="x", action_url=url, action_label="继续", resume_hint="返回", intent_summary="测试")
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest backend/tests/unit/chatloop/test_outcomes.py -q`

Expected: FAIL because the contract does not exist.

- [ ] **Step 3: Implement the frozen contract**

```python
class ActionRequiredOutcome(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    code: Literal["action_required"] = "action_required"
    action_type: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    action_url: str = Field(min_length=1, max_length=512, pattern=r"^/(?!/)")
    action_label: str = Field(min_length=1, max_length=80)
    resume_hint: str = Field(min_length=1, max_length=240)
    intent_summary: str = Field(min_length=1, max_length=500)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest backend/tests/unit/chatloop/test_outcomes.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/chatloop/outcomes.py backend/tests/unit/chatloop/test_outcomes.py
git commit -m "feat(chat): define action-required outcome"
```

### Task 2: Persist outcomes without adding a Run status

**Files:**
- Modify: `backend/app/models/run.py`
- Modify: `backend/app/chatloop/run_executor.py`
- Modify: `backend/app/services/attempt_service.py`
- Test: `backend/tests/integration/test_run_chat_worker_pg.py`

- [ ] **Step 1: Write failing persistence tests**

```python
async def test_complete_chat_persists_action_required_as_completed(attempt_service, assignment):
    outcome = ActionRequiredOutcome(
        action_type="apply_market_permission",
        action_url="/market-permissions/star/apply",
        action_label="申请科创板权限",
        resume_hint="完成后返回",
        intent_summary="买入中芯国际 100 股",
    )
    await attempt_service.complete_chat(assignment, completed_result(outcome=outcome))
    run = await load_run(assignment.run_id)
    assert run.status == "completed"
    assert run.outcome_code == "action_required"
    assert run.outcome_payload["action_type"] == "apply_market_permission"
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest backend/tests/integration/test_run_chat_worker_pg.py -k action_required -q`

Expected: FAIL because `CompletedResult` and `Run` have no outcome.

- [ ] **Step 3: Add optional outcome and durable columns**

```python
@dataclass(frozen=True)
class CompletedResult:
    run_id: UUID
    attempt_id: UUID
    session_id: UUID
    final_text: str
    usage: RunUsage
    tools: tuple[ToolExecution, ...]
    events: tuple[RunEvent, ...]
    outcome: ActionRequiredOutcome | None = None
```

Add nullable `outcome_code VARCHAR(64)` and `outcome_payload JSONB` to `Run`, with a check constraint requiring both null or `outcome_code='action_required'` plus a non-null payload. In `complete_chat`, validate and deep-copy the payload, persist it in the same transaction as `final_message_id`, and include it in the durable `run.completed` event.

- [ ] **Step 4: Run terminal-race and persistence tests**

Run: `uv run pytest backend/tests/integration/test_run_chat_worker_pg.py backend/tests/unit/chatloop/test_run_executor.py -q`

Expected: PASS; existing ordinary completion stores null outcome fields.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/models/run.py backend/app/chatloop/run_executor.py backend/app/services/attempt_service.py backend/tests/integration/test_run_chat_worker_pg.py backend/tests/unit/chatloop/test_run_executor.py
git commit -m "feat(run): persist terminal action outcomes"
```

### Task 3: Upgrade existing Run schemas canonically

**Files:**
- Modify: `backend/app/scripts/migrate_phase3_execution_schema.py`
- Test: `backend/tests/integration/test_run_control_schema_upgrade.py`

- [ ] **Step 1: Add failing migration tests**

```python
def test_upgrade_adds_validated_run_outcome_columns(legacy_engine):
    migrate_phase3_execution_schema(legacy_engine)
    assert run_outcome_columns_are_canonical(legacy_engine)
    assert migrate_phase3_execution_schema(legacy_engine) == ()
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest backend/tests/integration/test_run_control_schema_upgrade.py -k outcome -q`

Expected: FAIL because outcome columns and the paired-null constraint are absent.

- [ ] **Step 3: Add idempotent DDL and catalog verification**

```sql
ALTER TABLE runs ADD COLUMN IF NOT EXISTS outcome_code VARCHAR(64);
ALTER TABLE runs ADD COLUMN IF NOT EXISTS outcome_payload JSONB;
ALTER TABLE runs ADD CONSTRAINT ck_runs_outcome_pair
CHECK (
  (outcome_code IS NULL AND outcome_payload IS NULL)
  OR (outcome_code = 'action_required' AND outcome_payload IS NOT NULL)
);
```

Verify column types and the normalized constraint expression, not only names.

- [ ] **Step 4: Run schema tests**

Run: `uv run pytest backend/tests/integration/test_run_control_schema_upgrade.py -q`

Expected: PASS, including wrong-definition rejection.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/scripts/migrate_phase3_execution_schema.py backend/tests/integration/test_run_control_schema_upgrade.py
git commit -m "feat(db): migrate durable run outcomes"
```

### Task 4: Expose outcome through snapshot and SSE

**Files:**
- Modify: `backend/app/schemas/run.py`
- Modify: `backend/app/schemas/run_session.py`
- Modify: `backend/app/router/runs.py`
- Modify: `backend/app/router/run_sessions.py`
- Test: `backend/tests/integration/test_runs_v1_router.py`
- Test: `backend/tests/integration/test_run_sessions_v1_router.py`

- [ ] **Step 1: Write failing API tests**

```python
def test_completed_run_snapshot_and_event_include_action(client, seeded_action_run, auth_headers):
    snapshot = client.get(seeded_action_run.url, headers=auth_headers).json()
    assert snapshot["outcome"]["code"] == "action_required"
    event = read_sse_event(client, seeded_action_run.events_url, "run.completed")
    assert event["outcome"]["action_url"] == "/market-permissions/star/apply"


def test_session_reload_includes_latest_terminal_action(client, seeded_action_run, auth_headers):
    detail = client.get(seeded_action_run.session_url, headers=auth_headers).json()
    assert detail["latest_run_outcome"]["code"] == "action_required"
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest backend/tests/integration/test_runs_v1_router.py backend/tests/integration/test_run_sessions_v1_router.py -k outcome -q`

Expected: FAIL because `RunResponse` omits outcome.

- [ ] **Step 3: Add a typed response field and event payload**

```python
class RunResponse(BaseModel):
    # existing fields remain unchanged
    outcome: ActionRequiredOutcome | None = None

    @classmethod
    def from_run(cls, run: Run) -> "RunResponse":
        data = {column.name: getattr(run, column.name) for column in Run.__table__.columns}
        data["outcome"] = (
            ActionRequiredOutcome.model_validate(run.outcome_payload)
            if run.outcome_code == "action_required"
            else None
        )
        return cls.model_validate(data)
```

Replace direct `RunResponse.model_validate(run)` calls with `RunResponse.from_run(run)`. SSE replay and live events must produce identical payloads.

Add `latest_run_outcome: ActionRequiredOutcome | None` to the session detail schema and populate it from the same latest Run snapshot used for `latest_run_id` and `latest_run_status`. This makes the card survive a browser reload without reopening an active Run.

- [ ] **Step 4: Run API tests**

Run: `uv run pytest backend/tests/integration/test_runs_v1_router.py backend/tests/integration/test_run_sessions_v1_router.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/schemas/run.py backend/app/schemas/run_session.py backend/app/router/runs.py backend/app/router/run_sessions.py backend/tests/integration/test_runs_v1_router.py backend/tests/integration/test_run_sessions_v1_router.py
git commit -m "feat(api): expose action-required run outcomes"
```

### Task 5: Render a generic action-required card

**Files:**
- Modify: `frontend/src/api/runApi.ts`
- Modify: `frontend/src/hooks/useRunSSE.ts`
- Modify: `frontend/src/pages/chat/session.tsx`
- Create: `frontend/src/components/chat/ActionRequiredCard.tsx`
- Create: `frontend/src/components/chat/ActionRequiredCard.module.scss`
- Modify: `frontend/src/components/chat/ChatPane.tsx`
- Test: `frontend/src/components/chat/__tests__/ActionRequiredCard.test.tsx`
- Test: `frontend/src/hooks/__tests__/useRunSSE.test.tsx`
- Test: `frontend/src/pages/chat/__tests__/session.test.tsx`

- [ ] **Step 1: Write failing hook and component tests**

```tsx
it('keeps completed status while exposing an action card', async () => {
  stream('run.completed', { content: '需要先开通权限', outcome: actionRequired })
  await waitFor(() => expect(result.current.status).toBe('completed'))
  expect(result.current.outcome).toEqual(actionRequired)
  expect(result.current.pause).toBeNull()
})

it('restores the latest action card from session detail after reload', () => {
  render(<ChatSessionPage />, { session: { latest_run_outcome: actionRequired } })
  expect(screen.getByRole('link', { name: '申请科创板权限' })).toBeVisible()
})


it('navigates to the internal action URL and never auto-sends a chat message', async () => {
  render(<ActionRequiredCard outcome={actionRequired} onContinue={onContinue} />)
  expect(screen.getByRole('link', { name: '申请科创板权限' })).toHaveAttribute('href', '/market-permissions/star/apply')
  expect(onContinue).not.toHaveBeenCalled()
})
```

- [ ] **Step 2: Verify RED**

Run: `npm test -- src/components/chat/__tests__/ActionRequiredCard.test.tsx src/hooks/__tests__/useRunSSE.test.tsx src/pages/chat/__tests__/session.test.tsx`

Workdir: `frontend`

Expected: FAIL because the type, hook state and card do not exist.

- [ ] **Step 3: Add types, state and card**

```ts
export interface ActionRequiredOutcome {
  code: 'action_required'
  action_type: string
  action_url: string
  action_label: string
  resume_hint: string
  intent_summary: string
}
```

`useRunSSE` stores the latest terminal outcome but still clears `activeRunId` and uses `completed`. `ChatPane` renders the card below the completed assistant message. The link uses React Router navigation. A separate “我已完成，继续” button calls `sendPrompt('我已完成外部操作，请重新检查并继续：' + intent_summary)`, thereby creating a new Run rather than resuming the old one.

Thread `latest_run_outcome` from `RunSessionDetail` through `frontend/src/pages/chat/session.tsx` into `ChatPane` and initialize the hook from it, so reload behavior matches live SSE behavior.

- [ ] **Step 4: Run tests and build**

Run: `npm test -- src/components/chat/__tests__/ActionRequiredCard.test.tsx src/hooks/__tests__/useRunSSE.test.tsx src/pages/chat/__tests__/session.test.tsx && npm run build`

Workdir: `frontend`

Expected: PASS and successful build.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/api/runApi.ts frontend/src/hooks/useRunSSE.ts frontend/src/pages/chat/session.tsx frontend/src/components/chat/ActionRequiredCard.tsx frontend/src/components/chat/ActionRequiredCard.module.scss frontend/src/components/chat/ChatPane.tsx frontend/src/components/chat/__tests__/ActionRequiredCard.test.tsx frontend/src/hooks/__tests__/useRunSSE.test.tsx frontend/src/pages/chat/__tests__/session.test.tsx
git commit -m "feat(frontend): render action-required outcomes"
```

### Task 6: Verify new-turn continuation and no implicit resume

**Files:**
- Create: `frontend/tests/e2e/action-required.spec.ts`
- Test: `backend/tests/e2e/test_action_required_run.py`

- [ ] **Step 1: Add end-to-end assertions**

```ts
test('external action ends the old run and continue creates a new run', async ({ page }) => {
  await seedCompletedActionRun(page)
  await page.goto('/chat/session-1')
  await expect(page.getByRole('link', { name: '申请科创板权限' })).toBeVisible()
  await page.getByRole('button', { name: '我已完成，继续' }).click()
  await expect.poll(() => createdRuns()).toHaveLength(1)
  expect(lastCreatedRun().replaces_run_id).toBeNull()
})
```

The backend e2e test must prove the old Run is terminal, has no unresolved pause, and cannot be resumed through `/resume`.

- [ ] **Step 2: Run focused suites**

Run: `uv run pytest backend/tests/e2e/test_action_required_run.py backend/tests/integration/test_runs_v1_router.py -q`

Run: `npx playwright test tests/e2e/action-required.spec.ts`

Workdir for Playwright: `frontend`

Expected: PASS. Record exact environment failures rather than replacing browser evidence with static checks.

- [ ] **Step 3: Commit**

```powershell
git add backend/tests/e2e/test_action_required_run.py frontend/tests/e2e/action-required.spec.ts
git commit -m "test: prove action-required continuation boundary"
```
