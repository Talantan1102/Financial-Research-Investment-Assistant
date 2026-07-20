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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def report_hash(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(payload.encode()).hexdigest()


def validate_backup_manifest(path: str | Path, *, database: str) -> bool:
    """Validate the small JSON manifest emitted by the pg_dump wrapper."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid backup manifest: {exc}") from exc
    if data.get("database") != database:
        raise ValueError("backup manifest database mismatch")
    if not data.get("timestamp"):
        raise ValueError("backup manifest timestamp missing")
    digest = str(data.get("sha256", ""))
    if len(digest) != 64 or any(c not in "0123456789abcdefABCDEF" for c in digest):
        raise ValueError("backup manifest sha256 missing or invalid")
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
) -> MigrationReport:
    if cleanup:
        if not confirm_drop_legacy_data:
            raise ValueError("cleanup requires --confirm-drop-legacy-data")
        if not database:
            raise ValueError("cleanup requires database name echo")
        if not backup_manifest:
            raise ValueError("cleanup requires --backup-manifest")
        validate_backup_manifest(backup_manifest, database=database)
    report = MigrationReport(applied=apply, database=database)
    # A fake/non-DB object is useful for command safety tests and produces an
    # empty, zero-write report.  Real sessions expose ``query``.
    if not hasattr(db, "query"):
        return report
    from sqlalchemy import select

    from app.models.chat import (
        ChatAttachment,
        ChatMessage,
        ChatSession,
        ChatSessionContext,
        LongTermMemory,
    )
    from app.models.research_report import ResearchReport
    from app.models.run import RunMessage, RunSession
    from app.models.tenant import TenantMembership

    sessions = list(db.scalars(select(ChatSession)))
    messages = list(db.scalars(select(ChatMessage)))
    report.source_counts.update(chat_sessions=len(sessions), chat_messages=len(messages))
    session_map: dict[Any, Any] = {}
    for row in sessions:
        try:
            membership = db.scalar(select(TenantMembership).where(TenantMembership.user_id == row.user_id).order_by(TenantMembership.joined_at))
            if membership is None:
                raise ValueError("no tenant membership")
            session_map[row.id] = membership.tenant_id
            if apply:
                target = db.get(RunSession, row.id)
                if target is None:
                    db.add(RunSession(id=row.id, tenant_id=membership.tenant_id, created_by_user_id=row.user_id, title=row.title, created_at=row.created_at, updated_at=row.updated_at))
                    report.writes += 1
        except Exception as exc:  # malformed/ambiguous rows are quarantined
            report.quarantined.append({"table": "chat_sessions", "id": str(getattr(row, "id", "")), "reason": str(exc)})
    for row in messages:
        tenant_id = session_map.get(row.session_id)
        if tenant_id is None:
            report.quarantined.append({"table": "chat_messages", "id": str(row.id), "reason": "session unresolved"})
            continue
        if apply and db.get(RunMessage, row.id) is None:
            db.add(RunMessage(id=row.id, tenant_id=tenant_id, session_id=row.session_id, role=row.role, content=row.content, status=getattr(row, "status", "done"), created_at=row.created_at))
            report.writes += 1
    # Repoint dependent records while retaining the legacy columns during the
    # compatibility window.  This makes the migration restartable and allows
    # consumers to switch independently before destructive cleanup.
    for row in list(db.scalars(select(ChatAttachment))):
        tenant_id = session_map.get(row.session_id)
        if tenant_id is not None and apply:
            row.run_session_id = row.session_id
            row.run_message_id = row.message_id
            report.writes += 1
    for row in list(db.scalars(select(ChatSessionContext))):
        if row.session_id in session_map and apply:
            row.run_session_id = row.session_id
            report.writes += 1
    for row in list(db.scalars(select(LongTermMemory))):
        if row.session_id in session_map and apply:
            row.run_session_id = row.session_id
            report.writes += 1
    for row in list(db.scalars(select(ResearchReport))):
        sid = getattr(row, "source_chat_session_id", None)
        if sid in session_map and apply:
            row.source_session_id = sid
            report.writes += 1
    report.target_counts.update(run_sessions=len(session_map), run_messages=sum(1 for m in messages if m.session_id in session_map))
    if apply:
        db.commit()
    if cleanup:
        if expected_report_hash and expected_report_hash != report.report_hash():
            raise ValueError("migration report hash mismatch")
        # Never silently issue destructive SQL: callers must provide an
        # explicit operator-approved cleanup hook.
        if not hasattr(db, "execute"):
            raise ValueError("database cleanup unavailable")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--cleanup", action="store_true")
    parser.add_argument("--confirm-drop-legacy-data", action="store_true")
    parser.add_argument("--database", default=None)
    parser.add_argument("--backup-manifest")
    parser.add_argument("--expected-report-hash")
    args = parser.parse_args()
    from app.core.database import SessionLocal
    with SessionLocal() as db:
        report = migrate_legacy_chat(db, **vars(args))
        print(json.dumps({**report.to_dict(), "report_hash": report.report_hash()}, sort_keys=True))


if __name__ == "__main__":
    main()
