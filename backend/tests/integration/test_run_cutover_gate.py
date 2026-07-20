from __future__ import annotations

from app.scripts.verify_run_cutover import CutoverEvidence, verify_cutover


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
