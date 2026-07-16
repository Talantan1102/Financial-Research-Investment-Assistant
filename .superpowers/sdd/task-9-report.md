# Task 9 Report: Production wiring、Phase 1 验收与 done card

## Outcome

- Added a shared async SQLAlchemy engine/session-factory builder and moved the PostgreSQL async URL helper out of `app_main.py` while preserving its compatibility re-export for existing workers/evals.
- Production lifespan now stores `db_async_engine` and `async_session_factory` before constructing `ChatSessionRepo`; a legacy repo construction failure no longer clears the Run API dependency.
- Mounted Tenant and Run routers before the retained v0 chat routers.
- Added production wiring, strict OpenAPI operation-set, shared factory, and metadata-registration tests.
- Added and indexed the Phase 1 done card with honest Phase 2 boundaries and observed verification limitations.
- Did not change or remove old `ChatTask`, old `/api/v0/chat`, or claim Scheduler/Worker/Redis/Celery/LLM execution.

## TDD evidence

### RED: production wiring

```powershell
$env:POSTGRES_PASSWORD='postgres123'
uv run --frozen --extra dev pytest backend/tests/integration/test_run_foundation_app_wiring.py -q
```

Observed exit 1: `2 failed, 1 passed`. The failures were the intended missing production `/api/v1/tenants`/Run paths and an empty Run-operation set. Foundation metadata already passed.

### RED: shared factory

After adding the factory contract test and before production code:

```text
ModuleNotFoundError: No module named 'app.core.async_database'
```

### GREEN

The focused Task 9 file then passed: `4 passed`, exit 0. It asserts the factory binds its returned sessionmaker to the returned engine, the production paths exist, OpenAPI has exactly the required six method/path pairs, and all nine foundation tables are registered.

## Verification evidence

- Phase 1 unit matrix: `200 passed`, exit 0.
- Phase 1 integration matrix: `49 passed`, exit 0.
- Exact plan ruff format scope: `547 files already formatted`, exit 0 after mechanically formatting `backend/app/models/run.py` and `backend/tests/unit/models/test_run_models.py` found by the first check.
- Exact plan ruff lint scope: `All checks passed!`, exit 0.
- Exact plan mypy scope: `Success: no issues found in 7 source files`, exit 0.
- Explicit production contract probe: six and only six Run operations; `missing_foundation_tables=[]`, exit 0.
- Wider `pytest backend/tests -q`: not green and not counted as acceptance evidence. Collection stopped with 28 errors due missing KB extras (`langchain_text_splitters`, `pymilvus`) and Windows lacking POSIX `resource`.

Passing pytest commands emitted pre-existing SQLAlchemy/Pydantic/`datetime.utcnow()` deprecation warnings.

## Phase boundary

Phase 1 persists and serves control-plane facts only. It has no Run scheduler, dispatcher, outbox, worker lease/claim, Redis token stream, Celery Run executor, or LLM invocation. Old v0 chat and `ChatTask` remain unchanged. Phase 2 starts from queued Runs and must add scheduling/claim/recovery through service-owned locked transactions and durable events.

## Independent review and fixes

Initial review of Task 9 plus `d2fea33f..290800b9` returned **NOT APPROVED** with 0 Critical, 2 Important, and 1 Minor:

1. `TenantQueueFull` returned 429 although the fixed plan contract requires 409.
2. Phase 1 SSE polled PostgreSQL for up to about 30 seconds although the plan requires close after one durable snapshot.
3. Minor: concurrent bootstrap processes can create more than one personal Tenant for a user; sequential reruns are idempotent, but the schema has no cross-process uniqueness guard.

Both Important findings were fixed in `a44f1238` (`fix(run): align phase 1 API contracts`) with TDD:

- RED: quota regression expected 409 and observed 429. GREEN: queue exhaustion maps to 409.
- RED: queued snapshot regression expected one event read and observed two. GREEN: the endpoint emits only the initial durable snapshot and closes; the terminal-race final drain remains part of that initial snapshot.
- Full Run router suite after the fixes: 21 passed; scoped Ruff format/lint and mypy exit 0.

The bootstrap concurrency item is recorded as a Minor follow-up and was not expanded into Task 9. Final re-review is pending and will be recorded before handoff.

## Commits

- `290800b9` — production wiring, factory, tests, done card, initial report.
- `a44f1238` — review fixes for exact HTTP and SSE Phase 1 contracts.
