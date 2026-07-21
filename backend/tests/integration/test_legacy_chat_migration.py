from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.scripts.migrate_legacy_chat_to_runs import (
    MigrationReport,
    migrate_legacy_chat,
    validate_backup_manifest,
)


def test_dry_run_report_is_json_and_has_zero_writes() -> None:
    class FakeDB:
        writes = 0

    db = FakeDB()
    report = migrate_legacy_chat(db, apply=False)
    assert isinstance(report, MigrationReport)
    assert report.applied is False
    assert report.writes == 0
    json.dumps(report.to_dict())
    assert db.writes == 0
    assert report.source_counts["escalation_records"] == 0
    assert report.dependency_counts["escalation_records"] == 0
    assert report.target_counts["run_escalation_records"] == 0


def test_cutover_report_counts_escalations_in_target_contract() -> None:
    report = MigrationReport(
        source_counts={"escalation_records": 3},
        dependency_counts={"escalation_records": 2},
        target_counts={"run_escalation_records": 2},
    )
    assert report.source_counts["escalation_records"] == 3
    assert report.dependency_counts["escalation_records"] == 2
    assert report.target_counts["run_escalation_records"] == 2


def test_cleanup_requires_explicit_confirmation_and_backup_manifest(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="confirm-drop-legacy-data"):
        migrate_legacy_chat(object(), apply=True, cleanup=True)

    manifest = tmp_path / "backup.json"
    manifest.write_text(
        json.dumps(
            {
                "database": "industry_assistant_test",
                "timestamp": "2026-07-20T00:00:00Z",
                "sha256": "a" * 64,
            }
        )
    )
    assert validate_backup_manifest(manifest, database="industry_assistant_test") is True


def test_migration_report_hash_is_stable() -> None:
    report = MigrationReport(source_counts={"chat_sessions": 1}, target_counts={"run_sessions": 1})
    assert report.report_hash() == report.report_hash()
