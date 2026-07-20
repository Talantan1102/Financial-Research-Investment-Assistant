# Run control schema migration

Phase 3 schema changes use a maintenance gate. A schema is fresh only when it
contains no SQLAlchemy application table and no schema-version marker
(`alembic_version` or `schema_migrations`). Web/API startup may call
`Base.metadata.create_all()` only for that fresh case.

If any application table or version marker already exists, startup performs the
complete Phase 3 contract check before any `create_all` or reconcile path. It
does not repair or create tables. Missing tables, partial upgrades, and drift
fail startup with the operator command below; this prevents a rolling web
process from taking an unbounded DDL lock.

From `backend/`, during a maintenance window with old writers stopped:

```powershell
..\.venv\Scripts\python.exe -m app.scripts.migrate_phase3_execution_schema `
  --lock-timeout-ms 5000 --statement-timeout-ms 300000
```

The migration is transactional and idempotent. It serializes with a PostgreSQL
advisory lock, deterministically repairs invalid or duplicate revision numbers
by `(created_at, id)`, and then adds
`uq_runs_tenant_session_revision_seq`. A lock timeout rolls the transaction
back; do not increase it during normal rolling startup. Restart the serving and
run-control processes only after the command succeeds.

The post-migration startup gate verifies only the Run execution contract, not
the unrelated application schema:

- `run_sessions.archived_at` and its index;
- `runs.revision_seq`, the tenant/session/revision unique constraint, and the
  replacement lookup index;
- every column type, nullability and server default on `run_tool_executions`
  and `run_usage_records`;
- their primary keys, provenance foreign keys, unique constraints, CHECK
  constraints, and model-declared indexes.

The command must finish successfully before starting any web, scheduler,
dispatcher, or worker process. A second invocation returning `()` is the
idempotency check. Do not use web startup as a migration command.

`backend/app/processes/run_control_init.py` is the Compose operator path and may
apply this migration before processes start. It is not part of the rolling web
startup path.
