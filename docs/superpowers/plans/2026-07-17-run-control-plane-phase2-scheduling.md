# Run Control Plane Phase 2 Scheduling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a PostgreSQL-authoritative Scheduler, Worker registry, Attempt lease lifecycle, Outbox Dispatcher, and simulated multi-worker execution path.

**Architecture:** FastAPI only creates durable queued Runs. SchedulingService atomically selects Tenant/Run/Worker and writes Attempt/Event/Outbox; Dispatcher sends at-least-once Redis notifications; workers must atomically claim PostgreSQL before executing. Redis accelerates delivery but never determines state.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, PostgreSQL, redis.asyncio, pytest, testcontainers Redis, Docker Compose.

---

## File map

- `backend/app/models/run_scheduling.py`: Worker, tenant cursor, and Outbox ORM only.
- `backend/app/run_control/mutations.py`: caller-owned-transaction Run lock/transition/event primitives.
- `backend/app/services/worker_registry.py`: registration, heartbeat, drain, and capacity snapshots.
- `backend/app/services/scheduling_service.py`: eligibility, fairness, priority, placement, atomic allocation, recovery.
- `backend/app/services/attempt_service.py`: claim, renew, simulated completion/failure/cancel acknowledgement.
- `backend/app/services/run_outbox.py`: transactional Outbox creation/claim/ack/retry.
- `backend/app/run_control/redis_transport.py`: Redis key/envelope serialization only.
- `backend/app/processes/run_scheduler.py`, `run_dispatcher.py`, `run_worker.py`: thin process loops.

### Task 1: Scheduling schema and transaction-bound mutations

**Files:**
- Create: `backend/app/models/run_scheduling.py`
- Create: `backend/app/run_control/mutations.py`
- Modify: `backend/app/models/run.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/run_control/types.py`
- Modify: `backend/app/services/run_service.py`
- Test: `backend/tests/unit/models/test_run_scheduling_models.py`
- Test: `backend/tests/unit/run_control/test_mutations.py`

- [ ] **Step 1: Write failing PostgreSQL model tests**

Pin the physical contract independently from production enums:

```python
WORKER_STATUSES = {"online", "draining", "offline"}
OUTBOX_TYPES = {"attempt.assigned", "attempt.cancel", "schedule.wake"}

def test_attempt_claim_fields_are_required_by_contract(db_session):
    columns = {c["name"] for c in inspect(db_session.get_bind()).get_columns("run_attempts")}
    assert {"claim_token", "claimed_at", "last_heartbeat_at"} <= columns

def test_outbox_dedupe_key_is_unique(db_session):
    assert "uq_run_outbox_dedupe_key" in unique_names(db_session, "run_outbox")
```

Also prove exact CHECK values, FKs, `next_attempt_at` index, tenant cursor PK, worker positive capacity, and fresh `Base.metadata.create_all()`.

- [ ] **Step 2: Run RED**

Run: `$env:POSTGRES_PASSWORD='postgres123'; uv run --frozen --extra dev pytest backend/tests/unit/models/test_run_scheduling_models.py -q`

Expected: FAIL because `app.models.run_scheduling` and new columns do not exist.

- [ ] **Step 3: Implement exact ORM and domain types**

Define:

```python
class WorkerStatus(StrEnum):
    ONLINE = "online"
    DRAINING = "draining"
    OFFLINE = "offline"

class OutboxType(StrEnum):
    ATTEMPT_ASSIGNED = "attempt.assigned"
    ATTEMPT_CANCEL = "attempt.cancel"
    SCHEDULE_WAKE = "schedule.wake"
```

`RunWorker`, `RunTenantScheduling`, and `RunOutbox` use UUID PKs, JSONB payloads, exact CHECKs, and composite FKs that preserve tenant/run/attempt/worker provenance. Extend `RunAttempt` with nullable claim fields because assigned-but-unclaimed rows are valid.

- [ ] **Step 4: Write failing mutation-store tests**

```python
async def test_transition_and_event_use_callers_transaction(factory, queued_run):
    async with factory() as session:
        async with session.begin():
            store = RunMutationStore(session)
            run = await store.lock_run(queued_run.tenant_id, queued_run.id)
            await store.transition(run, RunStatus.ASSIGNED, "run.assigned", {})
            await session.rollback()
    assert await reload_status(factory, queued_run.id) == "queued"
```

Also prove monotonic event seq under two callers and that store methods never commit.

- [ ] **Step 5: Extract `RunMutationStore` and rewire `RunService`**

Public interface:

```python
class RunMutationStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
    async def lock_run(self, tenant_id: UUID, run_id: UUID) -> Run:
        raise NotImplementedError
    async def transition(self, run: Run, target: RunStatus, event_type: str,
                         payload: Mapping[str, Any], attempt_id: UUID | None = None) -> RunEvent:
        raise NotImplementedError
```

Keep `RunService` transaction ownership and existing HTTP behavior unchanged. Add ScheduleWake Outbox to create/resume and Cancel Outbox only for assigned/running cancellation, in the same transaction.

- [ ] **Step 6: Run regression and commit**

Run:

```powershell
$env:POSTGRES_PASSWORD='postgres123'
uv run --frozen --extra dev pytest backend/tests/unit/models/test_run_models.py backend/tests/unit/models/test_run_scheduling_models.py backend/tests/unit/run_control backend/tests/unit/services/test_run_service_create.py backend/tests/unit/services/test_run_service_lifecycle.py -q
uv run --frozen --extra dev ruff check backend/app/models backend/app/run_control backend/app/services/run_service.py
uv run --frozen --extra dev mypy backend/app/run_control/mutations.py backend/app/services/run_service.py
```

Expected: all selected tests pass. Commit: `feat(run): add scheduling persistence primitives`.

### Task 2: Worker registry and capacity fencing

**Files:**
- Create: `backend/app/services/worker_registry.py`
- Test: `backend/tests/unit/services/test_worker_registry.py`

- [ ] **Step 1: Write failing real-PostgreSQL tests**

```python
worker = await registry.register(capacity=2, metadata={"pid": 123})
assert worker.worker_type == "chat"
await registry.heartbeat(worker.id)
await registry.drain(worker.id)
assert (await registry.get(worker.id)).status == "draining"
```

Test new UUID per registration, stale-heartbeat exclusion, positive capacity, drain preventing new placement, and active load derived only from unexpired assigned/running Attempts.

- [ ] **Step 2: Run RED**

Run: `uv run --frozen --extra dev pytest backend/tests/unit/services/test_worker_registry.py -q`

Expected: FAIL with missing `WorkerRegistry`.

- [ ] **Step 3: Implement registry**

```python
@dataclass(frozen=True)
class WorkerSnapshot:
    id: UUID
    capacity: int
    active_attempts: int
    heartbeat_at: datetime

class WorkerRegistry:
    async def register(self, capacity: int, metadata: Mapping[str, Any]) -> WorkerSnapshot:
        raise NotImplementedError
    async def heartbeat(self, worker_id: UUID) -> None:
        raise NotImplementedError
    async def drain(self, worker_id: UUID) -> None:
        raise NotImplementedError
    async def mark_offline(self, worker_id: UUID) -> None:
        raise NotImplementedError
```

Use database UTC time for liveness comparisons. Registry owns transactions; Scheduler uses transaction-bound query helpers in SchedulingService rather than calling registry methods mid-transaction.

- [ ] **Step 4: Run tests and commit**

Run target tests plus Ruff/mypy. Expected: pass. Commit: `feat(run): register durable chat workers`.

### Task 3: Scheduler policy and atomic allocation

**Files:**
- Create: `backend/app/run_control/scheduling_policy.py`
- Create: `backend/app/services/scheduling_service.py`
- Test: `backend/tests/unit/run_control/test_scheduling_policy.py`
- Test: `backend/tests/unit/services/test_scheduling_service.py`

- [ ] **Step 1: Write pure policy RED tests**

```python
assert effective_queued_at(resumed, boost_seconds=30) == resumed.queued_at - timedelta(seconds=30)
assert choose_worker([half_full, empty]).id == empty.id
assert retry_decision(cancel_requested, retry_count=0) == RecoveryDecision.CANCEL
```

Cover eligibility reasons, A1/B1/C1/A2 fairness, FIFO, finite resume boost, stable worker tie-breaking, and retry exhaustion.

- [ ] **Step 2: Implement pure policy**

No SQLAlchemy imports. Define immutable candidates and `EligibilityReason`, `RecoveryDecision`, `effective_queued_at()`, `rank_workers()`.

- [ ] **Step 3: Write transaction/concurrency RED tests**

Use two independent async sessions and `asyncio.gather()` to prove:

```python
results = await asyncio.gather(scheduler_a.schedule_once(), scheduler_b.schedule_once())
assert sum(result is not None for result in results) == 1
assert await attempt_count(run.id) == 1
```

Also prove capacity is not exceeded, Tenant round-robin, resume finite boost, Outbox/Event/Attempt rollback together, and no allocation to stale/draining Worker.

- [ ] **Step 4: Implement `schedule_once()`**

Lock in order: tenant cursor, Run, Worker. Recheck every predicate after locks. Create Attempt `attempt_no = max + 1`, lease from database time, transition Run assigned, create Event and deduped Assignment Outbox, update cursors, commit once.

```python
@dataclass(frozen=True)
class Assignment:
    run_id: UUID
    attempt_id: UUID
    worker_id: UUID
    lease_expires_at: datetime
```

- [ ] **Step 5: Run tests and commit**

Run policy, service, Phase 1 service/model tests, Ruff/mypy. Commit: `feat(run): schedule runs fairly and atomically`.

### Task 4: Attempt claim, lease, terminal commands, and recovery

**Files:**
- Create: `backend/app/services/attempt_service.py`
- Modify: `backend/app/services/scheduling_service.py`
- Test: `backend/tests/unit/services/test_attempt_service.py`
- Test: `backend/tests/unit/services/test_attempt_recovery.py`

- [ ] **Step 1: Write claim/fencing RED tests**

Prove duplicate claim has exactly one winner, wrong Worker fails, expired lease cannot claim, claim confirms Assignment Outbox, renew requires token, and an expired/zombie token cannot complete.

```python
first, second = await asyncio.gather(service.claim(cmd), service.claim(cmd))
assert sorted(result.claimed for result in (first, second)) == [False, True]
```

- [ ] **Step 2: Implement AttemptService**

```python
@dataclass(frozen=True)
class ClaimedAssignment:
    tenant_id: UUID
    run_id: UUID
    attempt_id: UUID
    worker_id: UUID
    claim_token: UUID
    lease_expires_at: datetime

@dataclass(frozen=True)
class ClaimResult:
    claimed: bool
    assignment: ClaimedAssignment | None

class AttemptService:
    async def claim(self, attempt_id: UUID, worker_id: UUID) -> ClaimResult:
        raise NotImplementedError
    async def renew(self, attempt_id: UUID, worker_id: UUID, token: UUID) -> datetime:
        raise NotImplementedError
    async def complete_simulated(self, attempt_id: UUID, worker_id: UUID, token: UUID,
                                 result: Mapping[str, Any]) -> None:
        raise NotImplementedError
    async def fail(self, attempt_id: UUID, worker_id: UUID, token: UUID,
                   error_code: str, error_message: str) -> None:
        raise NotImplementedError
    async def acknowledge_cancel(self, attempt_id: UUID, worker_id: UUID,
                                 token: UUID) -> None:
        raise NotImplementedError
```

Every mutation locks Attempt then Run, checks database time and claim token, writes durable Event in the same transaction.

- [ ] **Step 3: Write and implement recovery tests**

Cover cancel-requested expiry, first crash requeue, second crash fail, resume not consuming retry, and completion/recovery race. `recover_expired_attempts(limit)` uses `FOR UPDATE SKIP LOCKED` and returns immutable recovery results.

- [ ] **Step 4: Run tests and commit**

Run Task 3/4 and Phase 1 lifecycle tests. Commit: `feat(run): claim attempts with lease fencing`.

### Task 5: Outbox Dispatcher and Redis transport

**Files:**
- Create: `backend/app/services/run_outbox.py`
- Create: `backend/app/run_control/redis_transport.py`
- Create: `backend/app/processes/run_dispatcher.py`
- Test: `backend/tests/unit/services/test_run_outbox.py`
- Test: `backend/tests/unit/run_control/test_redis_transport.py`
- Test: `backend/tests/integration/test_run_dispatcher_redis.py`

- [ ] **Step 1: Write Outbox RED tests**

Test concurrent batch claim, lock expiry, exponential retry with cap, Assignment re-delivery until acknowledged, ScheduleWake one-shot confirmation, and Dispatcher crash after XADD before delivered update.

- [ ] **Step 2: Implement Outbox repository/service**

```python
class RunOutboxService:
    async def claim_batch(self, dispatcher_id: UUID, limit: int) -> tuple[OutboxItem, ...]:
        raise NotImplementedError
    async def mark_delivered(self, item_id: UUID) -> None:
        raise NotImplementedError
    async def mark_failed(self, item_id: UUID, error: str) -> None:
        raise NotImplementedError
```

Define `OutboxItem` in the same module as an immutable projection containing id, event type, run/attempt/worker IDs, payload and delivery attempt count; Redis code must not receive ORM rows.

All timing uses database time; error text is bounded and credential-safe.

- [ ] **Step 3: Implement Redis envelopes and Dispatcher loop**

Assignment key is `run:worker:{worker_id}:assignments`; cancel key is `run:attempt:{attempt_id}:control`; scheduler wake uses `run:scheduler:wake`. Serialize JSON with version 1 and UUID strings. The process loop supports `dispatch_once()` for deterministic tests and signal-driven shutdown.

- [ ] **Step 4: Run fakeredis and true Redis tests**

Run: `$env:POSTGRES_PASSWORD='postgres123'; uv run --frozen --extra dev pytest backend/tests/unit/services/test_run_outbox.py backend/tests/unit/run_control/test_redis_transport.py backend/tests/integration/test_run_dispatcher_redis.py -q`

Expected: pass with testcontainers Redis or configured local Redis. Commit: `feat(run): dispatch durable outbox notifications`.

### Task 6: Scheduler/worker processes and Phase 2 acceptance

**Files:**
- Create: `backend/app/processes/run_scheduler.py`
- Create: `backend/app/processes/run_worker.py`
- Create: `backend/tests/helpers/simulated_run_executor.py`
- Create: `backend/tests/integration/test_run_control_multi_process.py`
- Modify: `docker-compose.yml`
- Create: `docs/claude-context/run-control-plane-phase2-scheduling-done.md`

- [ ] **Step 1: Write simulated worker RED tests**

The simulated executor accepts delay/result/crash instructions but only calls public AttemptService methods. Test two workers complete different Sessions concurrently, duplicate Redis assignment executes once, same Session never has two active Runs, and process death triggers recovery.

- [ ] **Step 2: Implement thin process loops**

Scheduler loop calls recovery then `schedule_once()` until no immediate work, waits on wake or poll timeout. Worker registers, heartbeats, XREADGROUPs assignments, claims, renews during simulation, and drains on SIGTERM. No process updates ORM directly.

- [ ] **Step 3: Add Compose profiles and health checks**

Add `run-scheduler-a`, `run-scheduler-b`, `run-dispatcher`, `run-worker-a`, and `run-worker-b` services under a `run-control` profile, all sharing PostgreSQL/Redis environment and using distinct Worker instance IDs generated at start.

- [ ] **Step 4: Execute Phase 2 gates**

Run unit/L1 suites, then Compose L2.5 scenario that kills a Worker and restarts Redis. Query PostgreSQL for exact Attempt/Event/Outbox terminal facts. Capture commands and counts in the done card.

- [ ] **Step 5: Commit**

Commit: `feat(run): complete phase 2 scheduling control plane`.
