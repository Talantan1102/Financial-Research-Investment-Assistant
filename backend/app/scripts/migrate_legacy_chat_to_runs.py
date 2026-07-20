"""One-way, repeatable migration of legacy chat state into the Run control plane.

The command is deliberately report-first: without ``--apply`` it performs no
flush/commit and emits a deterministic JSON report.  Cleanup is a separate,
explicitly guarded operation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass
class MigrationReport:
    source_counts: dict[str, int] = field(default_factory=dict)
    target_counts: dict[str, int] = field(default_factory=dict)
    quarantined: list[dict[str, str]] = field(default_factory=list)
    writes: int = 0
    applied: bool = False
    database: str | None = None
    dependency_counts: dict[str, int] = field(default_factory=dict)
    mappings: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def report_hash(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(payload.encode()).hexdigest()


_LEGACY_TABLES = (
    "chat_tasks",
    "chat_session_context",
    "chat_attachments",
    "chat_messages",
    "chat_sessions",
)


def _maintenance_bootstrap(db: Any) -> None:
    """Create the run-side schema and compatibility columns in an explicit gate.

    Legacy installations predate ``run_*`` tables.  Selecting an ORM model
    before this gate would compile references to columns that do not exist.
    This helper is deliberately called only for ``--apply`` and runs in the
    same database, after rolling back the read-only inspection transaction.
    """
    from sqlalchemy import inspect, text

    from app.core.database import Base
    from app.models.escalation_record import EscalationRecord
    from app.models.research_report import ResearchReport
    from app.models.run import Run, RunMessage, RunSession
    from app.models.tenant import Tenant, TenantMembership
    from app.models.user import User

    bind = db.get_bind()
    db.rollback()
    # Existing maintenance migrations are the canonical run schema gate. They
    # are idempotent and protected by the same advisory lock as startup.
    from app.processes.run_control_init import initialize_schema

    initialize_schema(bind)
    with bind.begin() as connection:
        Base.metadata.create_all(
            bind=connection,
            tables=[
                User.__table__,
                Tenant.__table__,
                TenantMembership.__table__,
                RunSession.__table__,
                RunMessage.__table__,
                Run.__table__,
                ResearchReport.__table__,
                EscalationRecord.__table__,
            ],
        )
        inspector = inspect(connection)
        bridge_columns = {
            "chat_attachments": {
                "tenant_id": "UUID",
                "run_session_id": "UUID",
                "run_message_id": "UUID",
            },
            "chat_session_context": {
                "run_session_id": "UUID REFERENCES run_sessions(id) ON DELETE SET NULL",
            },
            "long_term_memories": {
                "run_session_id": "UUID REFERENCES run_sessions(id) ON DELETE SET NULL",
            },
            "research_reports": {
                "source_session_id": "UUID REFERENCES run_sessions(id) ON DELETE SET NULL",
                "source_run_id": "UUID REFERENCES runs(id) ON DELETE SET NULL",
            },
            "escalation_records": {
                # nullable during the bridge phase; rows are backfilled below
                # before the final NOT NULL gate is applied by the operator.
                "source_session_id": "UUID",
                "source_run_id": "UUID",
            },
        }
        for table, columns in bridge_columns.items():
            if not inspector.has_table(table):
                continue
            existing = {column["name"] for column in inspect(connection).get_columns(table)}
            for column, definition in columns.items():
                if column not in existing:
                    connection.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {definition}'))
        if inspector.has_table("escalation_records"):
            # Replace the legacy chat FK, if present, with run-native FKs only
            # after the migration has populated the bridge columns.
            for fk in inspector.get_foreign_keys("escalation_records"):
                if (fk.get("referred_table") or "") == "chat_sessions" and fk.get("name"):
                    connection.execute(text(f'ALTER TABLE escalation_records DROP CONSTRAINT IF EXISTS "{fk["name"]}"'))
            connection.execute(text("""
                DO $$ BEGIN
                  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_escalation_source_session') THEN
                    ALTER TABLE escalation_records ADD CONSTRAINT fk_escalation_source_session
                      FOREIGN KEY (source_session_id) REFERENCES run_sessions(id) ON DELETE RESTRICT;
                  END IF;
                  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_escalation_source_run') THEN
                    ALTER TABLE escalation_records ADD CONSTRAINT fk_escalation_source_run
                      FOREIGN KEY (source_run_id) REFERENCES runs(id) ON DELETE RESTRICT;
                  END IF;
                END $$
            """))
        if inspector.has_table("chat_attachments"):
            # Older installs created single-column FKs to globally unique
            # ids.  RunMessage ids are only unique within tenant/session, so
            # replace those constraints with the provenance-safe composite FK.
            for fk in inspector.get_foreign_keys("chat_attachments"):
                if (fk.get("referred_table") or "") in {"run_messages", "run_sessions"}:
                    name = fk.get("name")
                    if name:
                        connection.execute(text(f'ALTER TABLE "chat_attachments" DROP CONSTRAINT IF EXISTS "{name}"'))
            connection.execute(text("""
                DO $$ BEGIN
                  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_chat_attachments_run_session') THEN
                    ALTER TABLE chat_attachments ADD CONSTRAINT fk_chat_attachments_run_session
                      FOREIGN KEY (tenant_id, run_session_id) REFERENCES run_sessions(tenant_id, id) ON DELETE SET NULL;
                  END IF;
                  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_chat_attachments_run_message') THEN
                    ALTER TABLE chat_attachments ADD CONSTRAINT fk_chat_attachments_run_message
                      FOREIGN KEY (tenant_id, run_session_id, run_message_id)
                      REFERENCES run_messages(tenant_id, session_id, id) ON DELETE SET NULL;
                  END IF;
                END $$
            """))
        connection.execute(
            text(
                """CREATE TABLE IF NOT EXISTS run_legacy_mappings (
                    source_table VARCHAR(128) NOT NULL,
                    source_id VARCHAR(128) NOT NULL,
                    target_table VARCHAR(128) NOT NULL,
                    target_id VARCHAR(128) NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (source_table, source_id),
                    UNIQUE (source_table, source_id)
                )"""
            )
        )


def _ensure_legacy_columns(db: Any, *, apply: bool, report: MigrationReport) -> bool:
    """Ensure ORM legacy projections are safe, without DDL in dry-run mode."""
    from sqlalchemy import inspect, text

    from app.models.chat import (
        ChatAttachment,
        ChatMessage,
        ChatSession,
        ChatSessionContext,
        LongTermMemory,
    )
    from app.models.research_report import ResearchReport

    required = (ChatSession, ChatMessage, ChatAttachment, ChatSessionContext, LongTermMemory, ResearchReport)
    inspector = inspect(db.get_bind())
    missing: list[str] = []
    for model in required:
        table = model.__table__.name
        if not inspector.has_table(table):
            continue
        existing = {column["name"] for column in inspector.get_columns(table)}
        for column in model.__table__.columns:
            if column.name not in existing:
                missing.append(f"{table}.{column.name}")
                if apply:
                    sql_type = column.type.compile(dialect=db.get_bind().dialect)
                    db.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{column.name}" {sql_type}'))
    if missing and not apply:
        report.quarantined.append({"table": "schema", "id": "legacy", "reason": "missing columns: " + ",".join(missing)})
        return False
    return True


def _record_mapping(db: Any, source_table: str, source_id: Any, target_table: str, target_id: Any) -> None:
    from sqlalchemy import text

    db.execute(
        text(
            """INSERT INTO run_legacy_mappings
               (source_table, source_id, target_table, target_id)
               VALUES (:source_table, :source_id, :target_table, :target_id)
               ON CONFLICT (source_table, source_id) DO NOTHING"""
        ),
        {
            "source_table": source_table,
            "source_id": str(source_id),
            "target_table": target_table,
            "target_id": str(target_id),
        },
    )


def validate_backup_manifest(path: str | Path, *, database: str, strict: bool = False) -> bool:
    """Validate the small JSON manifest emitted by the pg_dump wrapper."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid backup manifest: {exc}") from exc
    if data.get("database") != database:
        raise ValueError("backup manifest database mismatch")
    timestamp = data.get("timestamp") or data.get("created_at")
    if not timestamp:
        raise ValueError("backup manifest timestamp missing")
    digest = str(data.get("sha256", ""))
    if len(digest) != 64 or any(c not in "0123456789abcdefABCDEF" for c in digest):
        raise ValueError("backup manifest sha256 missing or invalid")
    if strict:
        dump_path = data.get("dump_path") or data.get("path") or data.get("file")
        if not dump_path:
            raise ValueError("backup manifest dump_path missing")
        dump = Path(dump_path)
        if not dump.is_file():
            raise ValueError("backup dump file missing")
        actual = hashlib.sha256(dump.read_bytes()).hexdigest()
        if actual.lower() != digest.lower():
            raise ValueError("backup dump sha256 mismatch")
        stat = dump.stat()
        expected_mtime = data.get("mtime")
        if expected_mtime is not None and abs(stat.st_mtime - float(expected_mtime)) > 2:
            raise ValueError("backup dump mtime mismatch")
        try:
            parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            if parsed.timestamp() > datetime.now(UTC).timestamp() + 300:
                raise ValueError("backup manifest timestamp is in the future")
        except ValueError:
            raise ValueError("backup manifest timestamp invalid") from None
        command = str(data.get("command", ""))
        if "pg_dump" not in command:
            raise ValueError("backup manifest lacks pg_dump evidence")
    return True


def migrate_legacy_chat(
    db: Any,
    *,
    apply: bool = False,
    cleanup: bool = False,
    confirm_drop_legacy_data: bool = False,
    database: str | None = None,
    backup_manifest: str | Path | None = None,
    expected_report_hash: str | None = None,
    prior_report: MigrationReport | dict[str, Any] | str | Path | None = None,
    batch_size: int = 100,
) -> MigrationReport:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    if cleanup:
        if not apply:
            raise ValueError("cleanup requires --apply")
        if not confirm_drop_legacy_data:
            raise ValueError("cleanup requires --confirm-drop-legacy-data")
        if not database:
            raise ValueError("cleanup requires database name echo")
        if not backup_manifest:
            raise ValueError("cleanup requires --backup-manifest")
        validate_backup_manifest(backup_manifest, database=database, strict=True)
        if not expected_report_hash:
            raise ValueError("cleanup requires expected report hash")
        if prior_report is None:
            raise ValueError("cleanup requires prior successful apply report")
        if isinstance(prior_report, (str, Path)):
            prior_report = json.loads(Path(prior_report).read_text(encoding="utf-8"))
        prior_data: dict[str, Any] = (
            prior_report.to_dict()
            if isinstance(prior_report, MigrationReport)
            else dict(prior_report) if isinstance(prior_report, dict) else {}
        )
        if not prior_data.get("applied") or prior_data.get("quarantined"):
            raise ValueError("prior migration report is not a successful apply")
        prior_hash = prior_data.get("report_hash") or MigrationReport(**{k: v for k, v in prior_data.items() if k in MigrationReport.__dataclass_fields__}).report_hash()
        if prior_hash != expected_report_hash:
            raise ValueError("migration report hash mismatch")
    report = MigrationReport(applied=apply, database=database)
    # A fake/non-DB object is useful for command safety tests and produces an
    # empty, zero-write report.  Real sessions expose ``query``.
    if not hasattr(db, "query"):
        return report
    if apply:
        _maintenance_bootstrap(db)
    if not _ensure_legacy_columns(db, apply=apply, report=report):
        return report
    from sqlalchemy import select

    from app.models.chat import (
        ChatAttachment,
        ChatMessage,
        ChatSession,
        ChatSessionContext,
        LongTermMemory,
    )
    from app.models.escalation_record import EscalationRecord
    from app.models.research_report import ResearchReport
    from app.models.run import RunMessage, RunSession
    from app.models.tenant import TenantMembership

    sessions = list(db.scalars(select(ChatSession)))
    messages = list(db.scalars(select(ChatMessage)))
    report.source_counts.update(chat_sessions=len(sessions), chat_messages=len(messages))
    session_map: dict[Any, Any] = {}
    for row in sessions:
        try:
            memberships = list(
                db.scalars(
                    select(TenantMembership)
                    .where(TenantMembership.user_id == row.user_id)
                    .order_by(TenantMembership.joined_at, TenantMembership.tenant_id)
                )
            )
            if not memberships:
                raise ValueError("no tenant membership")
            if len(memberships) > 1:
                raise ValueError("ambiguous tenant membership; tenant selector required")
            membership = memberships[0]
            session_map[row.id] = membership.tenant_id
            if apply:
                target = db.get(RunSession, row.id)
                if target is None:
                    db.add(RunSession(id=row.id, tenant_id=membership.tenant_id, created_by_user_id=row.user_id, title=row.title, created_at=row.created_at, updated_at=row.updated_at))
                    report.writes += 1
            report.mappings[f"chat_sessions:{row.id}"] = f"run_sessions:{row.id}"
            if apply:
                _record_mapping(db, "chat_sessions", row.id, "run_sessions", row.id)
        except Exception as exc:  # malformed/ambiguous rows are quarantined
            report.quarantined.append({"table": "chat_sessions", "id": str(getattr(row, "id", "")), "reason": str(exc)})
        if apply and len(session_map) % batch_size == 0:
            db.commit()
    for row in messages:
        tenant_id = session_map.get(row.session_id)
        if tenant_id is None:
            report.quarantined.append({"table": "chat_messages", "id": str(row.id), "reason": "session unresolved"})
            continue
        if apply and tenant_id is not None and db.get(RunMessage, row.id) is None:
            db.add(RunMessage(id=row.id, tenant_id=tenant_id, session_id=row.session_id, role=row.role, content=row.content, status=getattr(row, "status", "done"), created_at=row.created_at))
            report.writes += 1
        if tenant_id is not None:
            report.mappings[f"chat_messages:{row.id}"] = f"run_messages:{row.id}"
            if apply:
                _record_mapping(db, "chat_messages", row.id, "run_messages", row.id)
    # Repoint dependent records while retaining the legacy columns during the
    # compatibility window.  This makes the migration restartable and allows
    # consumers to switch independently before destructive cleanup.
    for model, table, sid_attr in (
        (ChatAttachment, "chat_attachments", "session_id"),
        (ChatSessionContext, "chat_session_context", "session_id"),
        (LongTermMemory, "long_term_memories", "session_id"),
        (ResearchReport, "research_reports", "source_chat_session_id"),
    ):
        for row in list(db.scalars(select(model))):
            try:
                sid = getattr(row, sid_attr, None)
                if sid not in session_map:
                    report.quarantined.append({"table": table, "id": str(getattr(row, "id", sid)), "reason": "session unresolved"})
                    continue
                if apply:
                    if model is ChatAttachment:
                        row.tenant_id = session_map[sid]
                        row.run_session_id = sid
                        row.run_message_id = row.message_id
                    elif model is ChatSessionContext or model is LongTermMemory:
                        row.run_session_id = sid
                    else:
                        row.source_session_id = sid
                    report.writes += 1
                report.mappings[f"{table}:{getattr(row, 'id', sid)}"] = f"run_sessions:{sid}"
                if apply:
                    _record_mapping(db, table, getattr(row, "id", sid), "run_sessions", sid)
            except Exception as exc:
                report.quarantined.append({"table": table, "id": str(getattr(row, "id", "")), "reason": str(exc)})
    # Escalation records are audit rows, not Run executions, but their source
    # provenance must move with the rest of the chat state.  During the bridge
    # window old rows may still expose session_id; read it once and persist
    # only source_session_id/source_run_id afterwards.
    if hasattr(db, "query"):
        legacy_escalation_sessions: dict[str, Any] = {}
        try:
            from sqlalchemy import inspect, text

            cols = {c["name"] for c in inspect(db.get_bind()).get_columns("escalation_records")}
            if "session_id" in cols:
                legacy_escalation_sessions = {
                    str(item.id): item.session_id
                    for item in db.execute(text("SELECT id, session_id FROM escalation_records WHERE session_id IS NOT NULL"))
                }
        except Exception:
            legacy_escalation_sessions = {}
        for row in list(db.scalars(select(EscalationRecord))):
            legacy_sid = legacy_escalation_sessions.get(str(row.id))
            sid = getattr(row, "source_session_id", None) or legacy_sid
            if sid not in session_map:
                report.quarantined.append({"table": "escalation_records", "id": str(row.id), "reason": "session unresolved"})
                continue
            if apply:
                row.source_session_id = sid
                report.writes += 1
            report.mappings[f"escalation_records:{row.id}"] = f"run_sessions:{sid}"
            if apply:
                _record_mapping(db, "escalation_records", row.id, "run_sessions", sid)
    report.target_counts.update(run_sessions=len(session_map), run_messages=sum(1 for m in messages if m.session_id in session_map))
    report.source_counts.update(
        chat_attachments=sum(1 for row in db.scalars(select(ChatAttachment))),
        chat_session_context=sum(1 for row in db.scalars(select(ChatSessionContext))),
        long_term_memories=sum(1 for row in db.scalars(select(LongTermMemory))),
        research_reports=sum(1 for row in db.scalars(select(ResearchReport))),
    )
    report.dependency_counts.update(
        chat_attachments=sum(1 for row in db.scalars(select(ChatAttachment)) if row.session_id in session_map),
        chat_session_context=sum(1 for row in db.scalars(select(ChatSessionContext)) if row.session_id in session_map),
        long_term_memories=sum(1 for row in db.scalars(select(LongTermMemory)) if row.session_id in session_map),
        research_reports=sum(1 for row in db.scalars(select(ResearchReport)) if getattr(row, "source_chat_session_id", None) in session_map),
    )
    report.target_counts.update(
        run_attachments=report.dependency_counts["chat_attachments"],
        run_session_context=report.dependency_counts["chat_session_context"],
        run_memories=report.dependency_counts["long_term_memories"],
        run_research_reports=report.dependency_counts["research_reports"],
    )
    if apply:
        # Once every escalation row has a resolvable RunSession, finish the
        # bridge atomically: enforce source provenance and remove the legacy
        # session_id column.  Quarantined rows keep the database recoverable
        # for a subsequent operator rerun.
        if not any(item.get("table") == "escalation_records" for item in report.quarantined):
            from sqlalchemy import inspect, text

            cols = {c["name"] for c in inspect(db.get_bind()).get_columns("escalation_records")}
            if "source_session_id" in cols:
                db.execute(text("ALTER TABLE escalation_records ALTER COLUMN source_session_id SET NOT NULL"))
            if "session_id" in cols:
                db.execute(text("ALTER TABLE escalation_records DROP COLUMN session_id"))
        db.commit()
    if cleanup:
        if not hasattr(db, "execute"):
            raise ValueError("database cleanup unavailable")
        # This is intentionally the only destructive path.  All checks above
        # happen before the first DROP, so dry-run/apply can never remove data.
        from sqlalchemy import inspect, text

        # Do not use CASCADE here. Discover every FK/object pointing at a
        # legacy table and fail closed on anything outside the explicit drop
        # set. This prevents an unreviewed view, rule, trigger, or extension
        # object from being removed accidentally.
        inspector = inspect(db.get_bind())
        external: list[str] = []
        for table in inspector.get_table_names():
            for fk in inspector.get_foreign_keys(table):
                referred = (fk.get("referred_table") or "").lower()
                if referred in _LEGACY_TABLES and table not in _LEGACY_TABLES:
                    external.append(f"fk:{table}.{fk.get('name') or '<unnamed>'}->{referred}")
        if external:
            raise ValueError("legacy cleanup blocked by external dependencies: " + ",".join(sorted(external)))
        dependency_rows = db.execute(text("""
            SELECT dependent.relname AS dependent_name,
                   referenced.relname AS referenced_name,
                   dependent.relkind AS dependent_kind
            FROM pg_depend dep
            JOIN pg_class dependent ON dependent.oid = dep.objid
            JOIN pg_class referenced ON referenced.oid = dep.refobjid
            JOIN pg_namespace dn ON dn.oid = dependent.relnamespace
            JOIN pg_namespace rn ON rn.oid = referenced.relnamespace
            WHERE dn.nspname = current_schema()
              AND rn.nspname = current_schema()
              AND referenced.relname IN ('chat_tasks', 'chat_session_context', 'chat_attachments', 'chat_messages', 'chat_sessions')
              AND dependent.relname NOT IN ('chat_tasks', 'chat_session_context', 'chat_attachments', 'chat_messages', 'chat_sessions')
              AND dependent.relkind NOT IN ('i', 'S')
        """)).all()
        if dependency_rows:
            details = ",".join(f"{r.dependent_name}->{r.referenced_name}" for r in dependency_rows)
            raise ValueError("legacy cleanup blocked by unknown database dependencies: " + details)
        db.execute(
            text(
                "DROP TABLE IF EXISTS "
                + ", ".join(f'"{table}"' for table in _LEGACY_TABLES)
                + " RESTRICT"
            )
        )
        db.commit()
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--cleanup", action="store_true")
    parser.add_argument("--confirm-drop-legacy-data", action="store_true")
    parser.add_argument("--database", default=None)
    parser.add_argument("--backup-manifest")
    parser.add_argument("--expected-report-hash")
    parser.add_argument("--prior-report")
    args = parser.parse_args()
    from app.core.database import SessionLocal
    with SessionLocal() as db:
        report = migrate_legacy_chat(db, **vars(args))
        print(json.dumps({**report.to_dict(), "report_hash": report.report_hash()}, sort_keys=True))


if __name__ == "__main__":
    main()
