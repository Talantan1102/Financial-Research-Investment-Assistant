# Phase 2 Task 1 Report: Scheduling persistence and transaction-bound mutations

## Outcome

- Added `RunWorker`, `RunTenantScheduling`, and `RunOutbox` PostgreSQL models with fixed worker/outbox literals, positive capacity, a globally unique dedupe key, an indexed `next_attempt_at`, and composite provenance foreign keys.
- Extended `RunAttempt` with nullable UUID worker/claim identity and claim/heartbeat timestamps. `worker_id` changed from the Phase 1 placeholder string to UUID so it can reference `RunWorker.id` and participate in the attempt/worker provenance key.
- Added `RunMutationStore`, which receives an `AsyncSession`, locks a Run, performs transitions, and appends monotonic events without owning begin/commit/rollback.
- Rewired `RunService` to retain all transaction and visibility ownership while reusing `RunMutationStore`.
- POST Run and resume now write stable ScheduleWake outbox rows in the same transaction. Idempotent POST replay does not write a second wake. Assigned/running cancellation writes one stable Cancel outbox; queued/waiting immediate cancellation does not.
- Did not add Worker registry, Scheduler, Dispatcher, Redis behavior, claim execution, or recovery algorithms.

## TDD evidence

### RED 1: scheduling models

```powershell
$env:POSTGRES_PASSWORD='postgres123'
uv run --frozen --extra dev pytest backend/tests/unit/models/test_run_scheduling_models.py -q
```

Observed exit 1 during collection: `1 error`, `0 tests`; `ModuleNotFoundError: No module named 'app.models.run_scheduling'`. This was the intended missing scheduling-model module.

GREEN: the same command passed `11 passed`. After self-review removed a redundant functional duplicate test that could be masked by an unrelated FK, the final model file contains 10 tests; the unique constraint remains directly verified through PostgreSQL reflection.

### RED 2: caller-owned mutation store

```powershell
$env:POSTGRES_PASSWORD='postgres123'
uv run --frozen --extra dev pytest backend/tests/unit/run_control/test_mutations.py -q
```

Observed exit 1 during collection: `1 error`, `0 tests`; `ModuleNotFoundError: No module named 'app.run_control.mutations'`.

GREEN: the same command passed `5 passed`. The tests use real PostgreSQL sessions and prove caller rollback, uncommitted invisibility to another session, authoritative event payloads, tenant-scoped locking, and two-caller monotonic sequence allocation.

### RED 3: transactional wake/cancel outbox behavior

```powershell
$env:POSTGRES_PASSWORD='postgres123'
uv run --frozen --extra dev pytest backend/tests/unit/services/test_run_service_create.py::test_create_writes_one_stable_schedule_wake_and_replay_does_not_duplicate_it backend/tests/unit/services/test_run_service_lifecycle.py::test_cancel_queued_finishes_immediately backend/tests/unit/services/test_run_service_lifecycle.py::test_cancel_running_requests_cooperative_cancellation backend/tests/unit/services/test_run_service_lifecycle.py::test_resume_waiting_keeps_same_run_and_resolves_pause -q
```

Observed exit 1: `3 failed, 1 passed`. Create/replay had zero wake rows, running cancel had zero cancel rows, and resume had zero wake rows. Queued immediate cancel already passed because it correctly had no worker-cancel row.

GREEN: the same four cases passed `4 passed` after the RunService transaction wiring.

### RED 4: assigned cancellation

Before restoring the assigned branch, the focused assigned-cancel test failed with `assert None is not None` because no Cancel outbox existed. Restoring the required `{assigned, running}` branch made the same focused test pass `1 passed`.

## Verification evidence

- Task 1 focused matrix: `190 passed` in 76.6 seconds.
- Expanded Phase 1 unit matrix plus Task 1 tests on the final code: `217 passed` in 117.3 seconds.
- Phase 1 integration router/wiring matrix: `49 passed` in 38.5 seconds.
- Ruff format check: `10 files already formatted`, exit 0.
- Ruff lint: `All checks passed!`, exit 0.
- Mypy: `Success: no issues found in 2 source files`, exit 0.
- Passing tests retain pre-existing SQLAlchemy, Pydantic, and `datetime.utcnow()` deprecation warnings.

## Deviations and scope notes

- No implementation-scope deviation: Worker registry, Scheduler, Dispatcher, Redis, claim, and lease recovery remain for later Phase 2 tasks.
- Phase 1's fake executor can put a Run into assigned/running without creating an Attempt. RunService still writes the required Cancel outbox in that compatibility case with nullable `attempt_id/worker_id`. Once a real Attempt exists, the outbox copies its Attempt/Worker identity and the composite FK enforces provenance.

## Specification review fix: partial-NULL attempt provenance

The first review found that PostgreSQL `MATCH SIMPLE` skips the original
`(run_id, attempt_id, worker_id)` foreign key whenever `worker_id` is NULL. That
allowed an outbox row to name a nonexistent or cross-Run Attempt when the
Attempt was assigned but not yet claimed.

### Review RED

Six literal PostgreSQL cases were added before the model fix:

1. both `attempt_id/worker_id` NULL ScheduleWake is valid;
2. non-NULL Attempt and NULL Worker is valid for assigned-unclaimed cancel;
3. nonexistent Attempt and NULL Worker is rejected;
4. cross-Run Attempt and NULL Worker is rejected;
5. non-NULL Worker and NULL Attempt is rejected;
6. Attempt and Worker mismatch is rejected.

The focused model command collected 16 cases and produced the expected
`3 failed, 13 passed`. Cases 3, 4, and 5 failed with
`Failed: DID NOT RAISE IntegrityError`; cases 1, 2, and 6 already behaved
correctly.

### Review GREEN and final verification

- Added `(run_id, attempt_id) -> run_attempts(run_id, id)` while retaining the
  three-column FK for Worker consistency.
- Added `worker_id IS NULL OR attempt_id IS NOT NULL`; deliberately did not use
  `MATCH FULL`, because an assigned-unclaimed Attempt is valid.
- Focused model file: `16 passed` in 26.7 seconds.
- Task 1 path matrix: `197 passed` in 84 seconds.
- Expanded unit matrix: `223 passed` in 119 seconds.
- Integration router/wiring matrix: `49 passed` in 38.7 seconds.
- Ruff format: `10 files already formatted`; Ruff lint: `All checks passed!`.
- Mypy: `Success: no issues found in 3 source files`.
- `git diff --check`: exit 0.

## Code-quality review fixes: upgrade path and transaction evidence

### Phase 1 -> Phase 2 schema upgrade

RED started with collection error
`ModuleNotFoundError: app.scripts.migrate_phase2_scheduling_schema`. The first
real-PostgreSQL implementation then exposed a dependency failure for a valid
legacy UUID: adding the Attempt->Worker FK failed with `ForeignKeyViolation`
because the newly-created `run_workers` table had no matching identity.

The final synchronous migration runs in one `Engine.begin()` transaction:

- creates the independent Worker table before dependent DDL;
- validates each non-empty legacy Worker value with PostgreSQL UUID cast inside
  a SAVEPOINT;
- converts `worker_id varchar` using `NULLIF(worker_id, '')::uuid`;
- backfills distinct legacy identities as safe `offline`, capacity-1 Workers;
- adds the three nullable claim/heartbeat columns, provenance unique, and
  Attempt->Worker FK only when absent;
- returns an empty change tuple on the second run.

The invalid legacy value test proves fail-fast and full DDL rollback: no Worker
table, no claim columns, varchar remains, and no new unique constraint.
`app_main` now runs this migration before full `Base.metadata.create_all()`.
Connection-class OperationalErrors still log a degraded warning; connected
PostgreSQL schema/DDL errors log an exception and re-raise. A SQLSTATE `55P03`
test prevents broad OperationalError swallowing.

Upgrade/startup focused tests: `5 passed`.

### Member lock predicate

RED: `RunMutationStore.lock_run()` rejected the new keyword with
`TypeError: unexpected keyword argument created_by_user_id`. GREEN adds an
optional creator predicate inside the `SELECT ... FOR UPDATE`; RunService passes
it only for members. The hidden-query transaction remains open while a second
transaction acquires the real row lock under a 250ms lock timeout, proving the
first query did not lock another member's Run.

### Resume/outbox rollback

A real PostgreSQL unique-dedupe conflict proves one transaction covers Run,
Pause, Event, and Outbox: after `IntegrityError`, the Run remains waiting, Pause
is unresolved, no `run.resumed` Event exists, and exactly the pre-existing
Outbox remains. Mutation sensitivity temporarily inserted an early commit; the
test failed with `InvalidRequestError: closed transaction`. The temporary line
was removed and the focused test returned to `1 passed`.

### Final verification after all review fixes

- Task 1 path matrix: `199 passed` in 88.7 seconds.
- Expanded unit matrix: `225 passed` in 114.3 seconds.
- Integration upgrade/router/wiring matrix: `54 passed` in 42.1 seconds.
- Ruff format: `13 files already formatted`; Ruff lint: `All checks passed!`.
- Mypy: `Success: no issues found in 5 source files`.
- `git diff --check`: exit 0.
