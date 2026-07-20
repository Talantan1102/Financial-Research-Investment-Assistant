"""Read-only parity gate for legacy chat cutover."""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

_LEGACY_TABLES = (
    "chat_tasks",
    "chat_session_context",
    "chat_attachments",
    "chat_messages",
    "chat_sessions",
)


@dataclass
class CutoverEvidence:
    migration_report_hash: str
    source_counts: dict[str, int]
    target_counts: dict[str, int]
    active_chat_tasks: int
    frontend_singular_chat_urls: int
    has_run_session_routes: bool
    has_phase2_phase3_gates: bool
    backup_manifest_valid: bool = False
    dependency_source_counts: dict[str, int] = field(default_factory=dict)
    dependency_target_counts: dict[str, int] = field(default_factory=dict)
    quarantine_count: int = 0
    allowed_quarantine_count: int = 0
    legacy_external_fks: int = 0
    legacy_tables: int = 0


@dataclass
class CutoverResult:
    ok: bool
    failures: list[str] = field(default_factory=list)


def verify_cutover(evidence: CutoverEvidence) -> CutoverResult:
    failures: list[str] = []
    if not evidence.migration_report_hash or evidence.source_counts.get("chat_sessions", 0) != evidence.target_counts.get("run_sessions", 0) or evidence.source_counts.get("chat_messages", 0) != evidence.target_counts.get("run_messages", 0):
        failures.append("migration_counts")
    if evidence.active_chat_tasks:
        failures.append("active_chat_tasks")
    if evidence.frontend_singular_chat_urls:
        failures.append("legacy_frontend_urls")
    if not evidence.has_run_session_routes:
        failures.append("run_session_routes")
    if not evidence.has_phase2_phase3_gates:
        failures.append("phase2_phase3_done_cards")
    if not evidence.backup_manifest_valid:
        failures.append("backup_manifest")
    if evidence.dependency_source_counts != evidence.dependency_target_counts:
        failures.append("dependency_counts")
    if evidence.quarantine_count != evidence.allowed_quarantine_count:
        failures.append("quarantine")
    if evidence.legacy_external_fks or evidence.legacy_tables:
        failures.append("legacy_dependencies")
    return CutoverResult(ok=not failures, failures=failures)


def collect_database_evidence(
    engine: object,
    *,
    migration_report: str | Path,
    backup_manifest_valid: bool = False,
    frontend_root: str | Path = "frontend/src",
) -> CutoverEvidence:
    """Build evidence from the database and checked-in artifacts.

    The JSON report is an input to compare against, never the source of truth:
    counts, legacy tables, foreign keys, and active ChatTask rows are queried
    from PostgreSQL.  Missing DB objects or artifacts fail closed.
    """
    from sqlalchemy import inspect, text

    report_data = json.loads(Path(migration_report).read_text(encoding="utf-8"))
    supplied_hash = str(report_data.pop("report_hash", ""))
    actual_hash = hashlib.sha256(
        json.dumps(report_data, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
    db = engine.connect()  # type: ignore[attr-defined]
    try:
        inspector = inspect(db)
        tables = set(inspector.get_table_names())
        required = {"run_sessions", "run_messages", "runs", "tenant_memberships"}
        if not required.issubset(tables):
            raise RuntimeError("run control tables missing")
        def count(table: str) -> int:
            if table not in tables:
                return 0
            return int(db.execute(text(f'SELECT count(*) FROM "{table}"')).scalar_one())
        source = dict(report_data.get("source_counts", {}))
        target = dict(report_data.get("target_counts", {}))
        # Once cleanup drops legacy tables, preserve the audited source counts
        # from the migration artifact; while they exist, replace them with
        # live counts so a forged report cannot pass.
        if "chat_sessions" in tables:
            source["chat_sessions"] = count("chat_sessions")
        if "chat_messages" in tables:
            source["chat_messages"] = count("chat_messages")
        target["run_sessions"] = count("run_sessions")
        target["run_messages"] = count("run_messages")
        active = 0
        if "chat_tasks" in tables:
            active = int(db.execute(text("SELECT count(*) FROM chat_tasks WHERE status IN ('queued','running')")).scalar_one())
        external_fks = 0
        for table in tables:
            for fk in inspector.get_foreign_keys(table):
                if (fk.get("referred_table") or "").lower() in _LEGACY_TABLES:
                    external_fks += 1
        legacy_count = sum(table in tables for table in _LEGACY_TABLES)
    finally:
        db.close()
    project_root = Path(__file__).resolve().parents[3]
    frontend = (project_root / frontend_root) if not Path(frontend_root).is_absolute() else Path(frontend_root)
    source_text = "\n".join(p.read_text(encoding="utf-8") for p in frontend.rglob("*.ts*")) if frontend.is_dir() else ""
    singular_urls = source_text.count("/chat/") + source_text.count("/chat?")
    for path in (
        project_root / "backend/app/tasks/title_generation.py",
        project_root / "backend/app/memory/recall_search.py",
    ):
        if path.is_file():
            text_body = path.read_text(encoding="utf-8")
            singular_urls += sum(text_body.count(token) for token in ("ChatSession", "ChatMessage", "chat_sessions", "chat_messages"))
    routes_ok = (project_root / "backend/app/router/run_sessions.py").exists() or (project_root / "backend/app/router/run.py").exists()
    gates_ok = any((project_root / "docs/claude-context").glob("run-control-plane-phase2*")) and any((project_root / "docs/claude-context").glob("run-control-plane-phase3*"))
    return CutoverEvidence(
        migration_report_hash=(supplied_hash if supplied_hash == actual_hash else ""),
        source_counts=source,
        target_counts=target,
        active_chat_tasks=active,
        frontend_singular_chat_urls=singular_urls,
        has_run_session_routes=routes_ok,
        has_phase2_phase3_gates=gates_ok,
        backup_manifest_valid=backup_manifest_valid,
        dependency_source_counts=dict(
            report_data.get("dependency_source_counts")
            or report_data.get("dependency_counts", {})
        ),
        dependency_target_counts=dict(
            report_data.get("dependency_target_counts")
            or {
                "chat_" + key.removeprefix("run_"): value
                for key, value in target.items()
                if key.startswith("run_")
            }
        ),
        quarantine_count=len(report_data.get("quarantined", [])),
        allowed_quarantine_count=0,
        legacy_external_fks=external_fks,
        legacy_tables=legacy_count,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--migration-report", required=True)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--backup-manifest")
    args = parser.parse_args()
    from sqlalchemy import create_engine
    engine = create_engine(args.database_url)
    backup_ok = False
    if args.backup_manifest:
        from app.scripts.migrate_legacy_chat_to_runs import validate_backup_manifest
        database_name = engine.url.database
        if not database_name:
            raise SystemExit("database URL must include a database name")
        validate_backup_manifest(args.backup_manifest, database=database_name, strict=True)
        backup_ok = True
    evidence = collect_database_evidence(
        engine,
        migration_report=args.migration_report,
        backup_manifest_valid=backup_ok,
    )
    result = verify_cutover(evidence)
    print(json.dumps({"ok": result.ok, "failures": result.failures}))
    raise SystemExit(0 if result.ok else 1)


if __name__ == "__main__":
    main()
