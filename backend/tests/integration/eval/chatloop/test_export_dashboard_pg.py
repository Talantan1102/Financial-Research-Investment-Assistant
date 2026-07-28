from __future__ import annotations

from pathlib import Path
from typing import Any

from eval.chatloop.artifact_store import ArtifactStore
from eval.chatloop.export_dashboard import export_history
from eval.chatloop.recorder import ChatloopEvalRecorder, TrialRecord
from sqlalchemy.orm import Session, sessionmaker


def test_export_history_includes_business_trial_summary(
    db_session: Session,
    tmp_path: Path,
) -> None:
    session_factory = sessionmaker(
        bind=db_session.connection(),
        expire_on_commit=False,
    )
    recorder = ChatloopEvalRecorder(session_factory=session_factory, initialize_schema=False)
    run_id = "run-export-business"
    recorder.record(_run(run_id), [])
    artifact = ArtifactStore(tmp_path / "artifacts").write(_artifact(run_id))
    recorder.record_trial(
        TrialRecord(
            trial_id=f"{run_id}.B1-01.0",
            run_id=run_id,
            case_id="B1-01",
            trial_index=0,
            suite_type="Capability",
            trial_status="valid",
            task_pass=True,
            task_score=100.0,
            failure_reason=None,
            artifact=artifact,
        )
    )

    output = tmp_path / "history.json"
    data = export_history(output, session_factory=session_factory)

    assert output.exists()
    assert data["schema_version"] == 2
    latest = data["latest"]
    assert latest["run_id"] == run_id
    assert latest["business"]["valid_trial_rate"] == 1.0
    assert latest["business"]["task_pass_rate"] == 1.0
    assert latest["business"]["release_eligible"] is False
    assert latest["business"]["cases"][0]["pass_power_k"] is True


def test_export_history_uses_stable_run_id_tiebreaker_for_same_timestamp(
    db_session: Session,
    tmp_path: Path,
) -> None:
    session_factory = sessionmaker(bind=db_session.connection(), expire_on_commit=False)
    recorder = ChatloopEvalRecorder(session_factory=session_factory, initialize_schema=False)
    recorder.record(_run("run-a"), [])
    recorder.record(_run("run-b"), [])

    data = export_history(tmp_path / "history.json", session_factory=session_factory)

    assert data["latest"]["run_id"] == "run-b"


def _run(run_id: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "created_at": "2026-07-28T12:00:00",
        "git_sha": "a" * 40,
        "mode": "business",
        "dispatch": "real",
        "sut_model": "test-model",
        "judge_model": "test-model",
        "simulator_model": None,
        "k": 1,
        "max_steps": 6,
        "max_turns": None,
        "golden_file": "catalog.json",
        "case_count": 1,
        "system_prompt_sha": "b" * 64,
        "thresholds_json": None,
        "sampling_json": {"sut": {"seed_applied": False}},
        "duration_ms": None,
        "cost_cny": None,
        "total_tokens": None,
        "status": "completed",
        "config_json": {},
    }


def _artifact(run_id: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "trial_id": f"{run_id}.B1-01.0",
        "run_id": run_id,
        "case_id": "B1-01",
        "trial_index": 0,
        "transcript": [{"role": "user", "content": "解释限价单"}],
        "tool_ledger": [],
        "database_before_after": {"before": {}, "after": {}},
        "versions": {
            "case": "cases-v1",
            "policy": "policy-v1",
            "evaluator": "business-eval-v1",
            "model": "test-model",
            "prompt_sha256": "b" * 64,
            "git_sha": "a" * 40,
        },
        "random_seed": 1,
        "duration_ms": 5,
        "cost": {"cny": 0.0, "total_tokens": 1},
        "evaluation": {"human_review_flags": []},
    }
