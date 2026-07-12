# Task 4 Report — SafeExecutor and ToolRuntime

## Scope

- Added the async `CapabilityAdapter` protocol and optional cancellation extension.
- Added `SafeExecutor` timeout, cancellation, exception, JSON/output-size enforcement.
- Added fail-closed `ToolRuntime` orchestration.
- Minimally extended `HookPipeline.run_pre(validate_input=True)` so runtime callers can
  defer validation until after permission without changing standalone Task 3 behavior.

## TDD evidence

- RED: target test collection failed with `ModuleNotFoundError: app.runtime.safe_executor`.
- GREEN: strict pipeline/order, effective-input validation, front-gate rejection,
  post-hook downgrade, timeout/cancel/exception/output-limit cases pass.
- Regression suite: all `backend/tests/unit/runtime` tests pass.

## Verification

- `uv run pytest backend/tests/unit/runtime -q`: 35 passed.
- `uv run mypy backend/app/runtime`: success, no issues.
- `uv run ruff check backend/app/runtime backend/tests/unit/runtime/test_tool_runtime.py`:
  all checks passed.
- Environment loaded from the main checkout's `backend/.env`; this worktree does not
  contain its own `backend/.env`.

## Commit

- `feat(runtime): add safe tool execution pipeline`

## Concerns

- `CapabilityRegistry.from_tool_registry()` still registers legacy `Tool` objects that
  expose `run()` rather than the new adapter `execute()` contract. That integration is
  explicitly Milestone 2 scope and requires a legacy-tool adapter.

## Review fix — effective-input permission request

- Added an explicit `PermissionRequest` carrying `capability_name`, `risk`, `input`,
  and `context` to the authorization callback.
- `ToolRuntime` now passes the pre-hook-adjusted `effective_input` into permission
  authorization before validation and execution.
- Regression coverage proves the callback sees the modified value and the adapter
  executes the exact same input object. Existing fail-closed behavior remains:
  `deny > ask > allow`, `ASK` without a callback becomes `DENY`, and `CRITICAL`
  does not prompt.

### Review-fix TDD and verification

- RED: focused test collection failed because `PermissionRequest` did not exist.
- GREEN: focused effective-input permission test passed.
- `uv run pytest backend/tests/unit/runtime -q`: 35 passed.
- `uv run mypy backend/app/runtime`: success, no issues in 10 source files.
- `uv run ruff check backend/app/runtime backend/tests/unit/runtime`: all checks passed.
- `git diff --check`: passed.
