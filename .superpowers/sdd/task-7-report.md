# Task 7 implementation report

## RED

- Baseline: Task 1 and Task 6 suites passed **112 tests** before Task 7 changes.
- Initial Task 7 command: `$env:POSTGRES_PASSWORD='postgres123'; uv run --frozen --extra dev pytest backend/tests/unit/services/test_run_service_lifecycle.py -q --tb=short`.
- The first fixture attempt errored because generated usernames exceeded the existing `VARCHAR(50)` constraint. The fixture was corrected before counting RED evidence.
- Valid RED: **10 failed**, all for the expected missing interfaces: `cancel_run`, `transition_run`, `record_pause`, and `resume_run`.

## GREEN

- Task 7 focused suite: **12 passed** using real PostgreSQL.
- Combined Task 1 + Task 6 + Task 7 suite: **124 passed**.
- Ruff format: 3 Task 7 code/test files already formatted.
- Ruff lint: all checks passed for the Task 7 code/test files.
- Mypy: no issues in `run_service.py` and `run_fake_executor.py`.
- `git diff --check`: exit 0.

## Implemented contract

- Every lifecycle mutation owns one transaction, first performs the same member/owner/admin visibility check used by reads, then locks the visible Run `FOR UPDATE`.
- Event sequence allocation happens after the Run lock and in the same transaction as the state mutation, preventing duplicate `(run_id, seq)` values under concurrent commands.
- queued/waiting cancel becomes `cancelled` with `finished_at`; assigned/running cancel becomes `cancel_requested` with `cancel_requested_at`; repeated cancel after a terminal or already-requested state is event-free and idempotent.
- `record_pause` only permits `running`, allocates `pause_no`, persists request and continuation payloads, transitions to the matching waiting state, and appends `run.paused` atomically.
- `resume_run` resolves the latest matching pause, persists its response, returns the same Run to `queued` with `queue_reason="resume"`, and appends one `run.resumed` event. A concurrent/repeated identical resume returns the already queued Run without resolving or appending twice.
- `FakeRunExecutor` drives tests only through public `RunService` commands; it never updates ORM rows directly.
- Concurrency coverage includes two Run mutations sharing event sequence allocation, two concurrent resumes, and cancel racing resume.

## Scope and deviations

- Task 1 already allowed `waiting_approval/input -> queued`, so no domain transition change was necessary.
- No Outbox, Redis, Celery, Scheduler, Worker, API, or ORM schema changes were added.
- The existing models use legacy untyped SQLAlchemy `Column` attributes. Production assignments use narrow `cast(Any, run)` expressions so the scoped mypy gate remains clean without changing Task 5 models.
- Existing SQLAlchemy `declarative_base()` and `datetime.utcnow()` warnings remain outside Task 7 scope.

## Independent review

- Initial review of commit `9a3409be`: **CHANGES REQUESTED**, 0 Critical, 2 Important, 0 Minor.
- Important 1: `get_pause(pause_id)` lacked tenant/member visibility checks. Regression RED failed with the old incompatible signature; the service now accepts tenant/run/actor scope, verifies Run visibility first, then filters pause by both pause and Run IDs. Tests cover outsider and same-tenant other-member access returning `ResourceNotFound`.
- Important 2: caller payload could overwrite durable event `from_status/status`. Regression RED showed the event claiming `failed -> completed` while the Run became `assigned`; authoritative fields are now merged last and cannot be spoofed.
- Reviewer also independently confirmed the Run lock makes cancel/resume and concurrent resume races legal, while event seq and pause_no allocation remain serialized.
- Re-review of amended commit `4b73d117`: **APPROVED**, 0 Critical, 0 Important. Reviewer re-ran lifecycle + Task 6 service tests (**31 passed**), Ruff, mypy, and `git diff --check`.
