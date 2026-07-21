from __future__ import annotations

import json
from hashlib import sha256

from app.scripts.verify_run_cutover import (
    CutoverEvidence,
    collect_database_evidence,
    verify_cutover,
)
from sqlalchemy import create_engine, text


def test_cutover_gate_requires_all_evidence() -> None:
    evidence = CutoverEvidence(
        migration_report_hash="ok",
        source_counts={"chat_sessions": 2},
        target_counts={"run_sessions": 2},
        active_chat_tasks=0,
        frontend_singular_chat_urls=0,
        has_run_session_routes=True,
        has_phase2_phase3_gates=True,
        backup_manifest_valid=True,
    )
    assert verify_cutover(evidence).ok is True


def test_cutover_gate_rejects_mismatch_and_active_legacy_tasks() -> None:
    evidence = CutoverEvidence(
        migration_report_hash="",
        source_counts={"chat_sessions": 2},
        target_counts={"run_sessions": 1},
        active_chat_tasks=1,
        frontend_singular_chat_urls=1,
        has_run_session_routes=False,
        has_phase2_phase3_gates=False,
    )
    result = verify_cutover(evidence)
    assert result.ok is False
    assert {"migration_counts", "active_chat_tasks", "legacy_frontend_urls"} <= set(result.failures)


def test_collect_database_evidence_reads_escalation_and_dependency_targets_live(tmp_path) -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE run_sessions (id TEXT)"))
        conn.execute(text("CREATE TABLE run_messages (id TEXT)"))
        conn.execute(text("CREATE TABLE runs (id TEXT)"))
        conn.execute(text("CREATE TABLE tenant_memberships (id TEXT)"))
        conn.execute(text("CREATE TABLE escalation_records (id TEXT, source_session_id TEXT)"))
        conn.execute(text("INSERT INTO run_sessions VALUES ('s1')"))
        conn.execute(text("INSERT INTO run_messages VALUES ('m1')"))
        conn.execute(text("INSERT INTO runs VALUES ('r1')"))
        conn.execute(text("INSERT INTO escalation_records VALUES ('e1', 's1'), ('e2', NULL)"))
    report = {
        "source_counts": {"chat_sessions": 999, "escalation_records": 999},
        "target_counts": {"run_sessions": 999, "run_messages": 999, "run_escalation_records": 999},
        "dependency_counts": {"escalation_records": 999},
        "quarantined": [],
    }
    report["report_hash"] = sha256(
        json.dumps(report, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    path = tmp_path / "migration.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    evidence = collect_database_evidence(engine, migration_report=path)
    assert evidence.source_counts["escalation_records"] == 2
    assert evidence.target_counts["run_escalation_records"] == 1
    assert evidence.dependency_target_counts["escalation_records"] == 1
