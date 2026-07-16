# Task 8 implementation report

## RED

- Command: `$env:POSTGRES_PASSWORD='postgres123'; uv run --frozen --extra dev pytest backend/tests/integration/test_runs_v1_router.py -q --tb=short`
- Result: collection exited 1 with `ModuleNotFoundError: No module named 'app.router.runs'`, the expected missing-router failure.
- The first GREEN attempt produced 10 failures because the composite FastAPI annotation treated the idempotency-key validator as a query dependency. The valid POST response was 422. The dependency was corrected to a single `Header` input wrapped by `Depends`, after which the focused 201/200 replay test passed.

## Implemented contract

- Exactly six operations are defined beneath `/api/v1/tenants/{tenant_id}/runs`: create, get, events, trace, cancel, and resume. No steering endpoint was added.
- Every operation reuses `get_current_user_required`; actor identity always comes from the authenticated `User.id`, while tenant and Run scope come from typed path parameters.
- `get_run_service(Request)` uses `app.state.async_session_factory`. The router delegates membership, owner/admin/member visibility, locking, idempotency, quota, and lifecycle semantics to `RunService`.
- Domain errors map to stable HTTP classes: concealed `ResourceNotFound` to 404; busy/idempotency/resume/transition conflicts to 409; queued quota to 429; malformed body, UUID, header, and event cursor inputs to 422.
- `Idempotency-Key` is required, non-blank, and capped at 128 UTF-8 bytes. A new create returns 201; an identical replay returns 200 and the same Run. `CreatedRun.replayed` is the minimal service metadata needed to distinguish those HTTP outcomes without an unsafe router-side preflight query.
- SSE emits durable PostgreSQL events as `id`, `event`, and JSON `data` fields. Both `Last-Event-ID` and `after_seq` are supported; the query cursor takes precedence. Cursor filtering prevents duplicate replay, terminal Runs close immediately, and nonterminal Runs use bounded polling with configurable interval/poll count. Tests set interval zero and never perform real long sleeps.
- Trace output follows the existing `TraceSpanRow` shape and preserves Run visibility checks before returning diagnostics.

## Verification before review

- Task 8 ASGI + real PostgreSQL suite: **21 passed** after review fixes.
- Combined Task 8 + Task 6 + Task 7 service regression command: **52 passed** after review fixes.
- The ASGI tests cover exact OpenAPI operations, unauthenticated 401, member/owner/admin/outsider visibility, idempotency replay/conflict, session busy, quota, cancel/resume, SSE framing/reconnect/terminal close, cursor validation, and trace visibility.
- Existing SQLAlchemy `declarative_base()`, Pydantic v1-style config, and `datetime.utcnow()` deprecation warnings remain outside Task 8 scope.

## Independent review

- Initial read-only review of `47eef16d..29f26601` found one Important SSE race: a terminal transition could commit between the separate event and status reads, causing the stream to observe terminal status and close before emitting the final durable event.
- RED: deterministic ASGI race test made `run.completed` visible during the status read and received only `[1]` instead of `[1, 2]`.
- Fix: `_read_durable_snapshot()` performs one final `seq > cursor` drain after terminal status is observed. Both initial subscription and polling use it; the caller yields every drained event and advances the cursor before returning.
- A second RED reproduced membership visibility being revoked after response headers, which previously surfaced as a StreamingResponse task-group failure. Polling now keeps the already-authorized snapshot and closes cleanly on `ResourceNotFound`.
- Re-review of `29f26601..b6b44bc2`: **APPROVED**, 0 Critical and 0 Important. The reviewer independently confirmed both initial and polling final-drain paths, cursor advancement before terminal return, clean post-header visibility revocation, 21 router tests, Ruff, and mypy.
