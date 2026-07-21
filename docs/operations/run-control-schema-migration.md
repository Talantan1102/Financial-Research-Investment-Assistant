# Run control schema migration

Run-control schema changes use a maintenance gate. A schema is fresh only when it
contains no SQLAlchemy application table and no schema-version marker
(`alembic_version` or `schema_migrations`). Web/API startup may call
`Base.metadata.create_all()` only for that fresh case.

Fresh detection, `create_all`, and verification run in one PostgreSQL
transaction-scoped advisory-lock critical section. A second web instance takes
the same lock and re-checks after the first commits, so it never races a second
`create_all`. If any application table or version marker already exists,
startup performs the complete Phase 2+3 run-control contract check before any
`create_all` or reconcile path. It does not repair or create tables. Missing
tables, partial upgrades, and drift
fail startup with the operator command below; this prevents a rolling web
process from taking an unbounded DDL lock.

From `backend/`, during a maintenance window with old writers stopped:

```powershell
..\.venv\Scripts\python.exe -m app.processes.run_control_init
```

The initialization is transactional and idempotent. It serializes with a
PostgreSQL advisory lock, deterministically repairs invalid or duplicate
revision numbers by `(created_at, id)`, and then adds
`uq_runs_tenant_session_revision_seq`. A lock timeout rolls the transaction
back. Restart the serving and run-control processes only after the command
succeeds; a second successful invocation is the idempotency check.

The post-migration startup gate verifies only the Run control-plane contract, not
the unrelated application schema:

- the Phase 1 Run facts (`run_sessions`, `run_messages`, `runs`,
  `run_attempts`, `run_pauses`, and `run_events`);
- Phase 2 scheduling (`run_workers`, `run_tenant_scheduling`, and `run_outbox`);
- Phase 3 execution (`run_tool_executions` and `run_usage_records`);
- every column, nullability, PostgreSQL type, server default, primary key,
  foreign key, CHECK, unique constraint, and model-declared index. Constraint
  semantics are compared independently of deployment-generated names.

The operator command must finish successfully before starting any web,
scheduler, dispatcher, or worker process. The Compose operator entrypoint exits
successfully without printing a change tuple. Do not use web startup as a
migration command.

`backend/app/processes/run_control_init.py` is the Compose operator path. It
takes the same outer advisory lock as web startup, then applies Phase 2 and
Phase 3 migrations in the documented lock order, creates any remaining current
tables, and runs the full read-only gate before committing. It is not part of
the rolling web startup path; ordinary startup never calls a maintenance
migrator.
