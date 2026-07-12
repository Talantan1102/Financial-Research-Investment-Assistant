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
