# Task 3 Report — Hook、Permission 和 InputGuard

## Outcome

- Added ordered pre/post hook pipeline with message aggregation, patch-style input merging, deny short-circuiting, and post-hook input revalidation.
- Added fail-closed permission engine with `deny > ask > allow`, capability minimum-risk floors, and explicit authorization callback handling.
- Added local MCP JSON Schema validation via `jsonschema` and rejected unknown fields when the schema uses `additionalProperties: false`.
- Declared `jsonschema>=4.23` as a direct base dependency because production runtime code imports it directly; it was previously present only transitively through `mcp`.

## TDD evidence

### RED

Command (with `/Users/talantan/.openclaw/workspace-main/financial-research-assistant/backend/.env` loaded):

```text
uv run pytest backend/tests/unit/runtime/test_policy_pipeline.py -v
```

Observed expected collection failure before implementation:

```text
ModuleNotFoundError: No module named 'app.runtime.hooks'
0 collected, 1 error
```

After the first minimal implementation, the suite exposed a real aggregation bug (`key` received a dict rather than a callable): 7 failed, 1 passed. Fixing `strictest` produced green tests.

### GREEN / final verification

```text
uv run pytest backend/tests/unit/runtime -v
25 passed, 2 warnings in 0.11s

uv run ruff check backend/app/runtime backend/tests/unit/runtime
All checks passed!

uv run mypy backend/app/runtime/hooks.py backend/app/runtime/permissions.py backend/app/runtime/validation.py backend/tests/unit/runtime/test_policy_pipeline.py
Success: no issues found in 4 source files

git diff --check
exit 0
```

Warnings are pre-existing SQLAlchemy `declarative_base` and testcontainers Redis deprecations.

## Self-review

- Hook `ALLOW` is always aggregated with the capability-derived floor, so it cannot lower `MEDIUM/HIGH` from `ASK`.
- Hook mutations are merged in registration order and the final effective input is validated after all pre-hooks.
- `DENY` stops remaining hooks immediately.
- `ASK` without a callback returns `DENY`; a callback must explicitly approve it.
- JSON Schema errors preserve the failing property path where available.

## Concerns

- Full runtime-test mypy currently reports a pre-existing unused `type: ignore` in `backend/tests/unit/runtime/test_models.py:110`; the new/changed Task 3 implementation and test files pass mypy cleanly.
- `HIGH` maps to `ASK` and `CRITICAL` maps to `DENY`; this is the conservative risk-floor mapping chosen because the brief specifies only that hook allow cannot lower the minimum risk.

## Commit

To be filled after commit.
