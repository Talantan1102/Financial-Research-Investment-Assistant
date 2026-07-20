# Run control schema migration

Phase 3 schema changes use a maintenance gate. Web/API process startup never
backfills `runs` or creates its revision constraint. It creates missing tables
for a brand-new database, then performs a read-only contract check. An existing
database on an older contract fails startup with the operator command below.

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

`backend/app/processes/run_control_init.py` is the Compose operator path and may
apply this migration before processes start. It is not part of the rolling web
startup path.
