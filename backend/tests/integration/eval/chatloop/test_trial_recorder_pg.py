from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from eval.chatloop.artifact_store import ArtifactReference, ArtifactStore
from eval.chatloop.policy_registry import Violation
from eval.chatloop.recorder import (
    ChatloopEvalRecorder,
    ChatloopEvalTrialRow,
    ChatloopEvalViolationRow,
    TrialRecord,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


def _session_factory(session: Session):
    @contextmanager
    def factory() -> Iterator[Session]:
        try:
            yield session
        except Exception:
            session.rollback()
            raise

    return factory


def _record(
    *,
    artifact: ArtifactReference,
    trial_id: str = "trial-invalid",
    status: str = "invalid_evidence",
    task_pass: bool | None = None,
    violations: tuple[Violation, ...] = (),
) -> TrialRecord:
    return TrialRecord(
        trial_id=trial_id,
        run_id="run-001",
        case_id="B6-01",
        trial_index=0,
        suite_type="Capability",
        trial_status=status,
        task_pass=task_pass,
        task_score=None,
        failure_reason="missing database snapshot" if status == "invalid_evidence" else None,
        artifact=artifact,
        violations=violations,
    )


def _artifact(tmp_path, *, trial_id: str) -> ArtifactReference:
    return ArtifactStore(tmp_path).write(
        {
            "schema_version": 1,
            "run_id": "run-001",
            "trial_id": trial_id,
            "case_id": "B6-01",
            "trial_index": 0,
            "transcript": [],
            "tool_ledger": [],
            "database_before_after": {"before": {}, "after": {}},
            "versions": {
                "case": "2026.1",
                "policy": "2026.1",
                "evaluator": "2026.1",
                "model": "fake-model",
                "prompt_sha256": "a" * 64,
                "git_sha": "deadbeef",
            },
            "random_seed": 7,
            "duration_ms": 123,
            "cost": {"cny": None, "total_tokens": None},
        }
    )


def test_trial_row_preserves_null_pass_for_invalid_evidence(db_session: Session, tmp_path) -> None:
    recorder = ChatloopEvalRecorder(
        session_factory=_session_factory(db_session),
        initialize_schema=False,
    )

    artifact = _artifact(tmp_path, trial_id="trial-invalid")
    recorder.record_trial(_record(artifact=artifact))

    row = db_session.get(ChatloopEvalTrialRow, "trial-invalid")
    assert row is not None
    assert row.trial_status == "invalid_evidence"
    assert row.task_pass is None
    assert row.artifact_sha256 == artifact.sha256
    assert row.failure_reason == "missing database snapshot"


def test_trial_policy_violations_are_searchable_and_keep_escalation_ids(
    db_session: Session,
    tmp_path,
) -> None:
    recorder = ChatloopEvalRecorder(
        session_factory=_session_factory(db_session),
        initialize_schema=False,
    )
    record = _record(
        artifact=_artifact(tmp_path, trial_id="trial-violation"),
        trial_id="trial-violation",
        status="valid",
        task_pass=False,
        violations=(
            Violation(
                policy_id="TRADE-CONFIRM",
                severity="C0",
                triggered_escalations=["TRADE-CONFIRM-E1"],
            ),
        ),
    )

    recorder.record_trial(record)

    rows = db_session.scalars(
        select(ChatloopEvalViolationRow).where(
            ChatloopEvalViolationRow.policy_id == "TRADE-CONFIRM",
            ChatloopEvalViolationRow.severity == "C0",
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].policy_id == "TRADE-CONFIRM"
    assert rows[0].severity == "C0"
    assert rows[0].triggered_escalations == ["TRADE-CONFIRM-E1"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("trial_id", "some-other-trial"),
        ("run_id", "some-other-run"),
        ("case_id", "B6-02"),
        ("trial_index", 1),
    ],
)
def test_recorder_rejects_an_artifact_from_a_different_trial_identity(
    db_session: Session,
    tmp_path,
    field: str,
    value: object,
) -> None:
    recorder = ChatloopEvalRecorder(
        session_factory=_session_factory(db_session),
        initialize_schema=False,
    )
    bundle = {
        "schema_version": 1,
        "run_id": "run-001",
        "trial_id": "trial-invalid",
        "case_id": "B6-01",
        "trial_index": 0,
        "transcript": [],
        "tool_ledger": [],
        "database_before_after": {"before": {}, "after": {}},
        "versions": {
            "case": "2026.1",
            "policy": "2026.1",
            "evaluator": "2026.1",
            "model": "fake-model",
            "prompt_sha256": "a" * 64,
            "git_sha": "deadbeef",
        },
        "random_seed": 7,
        "duration_ms": 123,
        "cost": {"cny": None, "total_tokens": None},
    }
    bundle[field] = value
    wrong_artifact = ArtifactStore(tmp_path).write(bundle)

    with pytest.raises(ValueError, match=field):
        recorder.record_trial(_record(artifact=wrong_artifact))

    assert db_session.get(ChatloopEvalTrialRow, "trial-invalid") is None


@pytest.mark.parametrize(
    "values",
    [
        {"trial_status": "broken", "task_pass": None},
        {"trial_status": "invalid_evidence", "task_pass": True},
        {"suite_type": "Unknown"},
        {"trial_index": -1},
        {"task_score": 101.0},
        {"artifact_sha256": "not-a-sha"},
    ],
)
def test_database_rejects_invalid_trial_invariants(
    db_session: Session,
    values: dict[str, object],
) -> None:
    row_values = {
        "trial_id": "invalid-row",
        "run_id": "run-001",
        "case_id": "B6-01",
        "trial_index": 0,
        "suite_type": "Capability",
        "trial_status": "valid",
        "task_pass": False,
        "task_score": 0.0,
        "failure_reason": None,
        "artifact_path": "/tmp/evidence.json",
        "artifact_sha256": "a" * 64,
        "created_at": "2026-07-28T00:00:00+00:00",
    }
    row_values.update(values)
    db_session.add(ChatloopEvalTrialRow(**row_values))

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_database_rejects_orphan_violation(db_session: Session) -> None:
    db_session.add(
        ChatloopEvalViolationRow(
            trial_id="missing-trial",
            policy_id="TRADE-CONFIRM",
            severity="C0",
            triggered_escalations=[],
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_database_rejects_invalid_violation_severity(db_session: Session) -> None:
    db_session.add(
        ChatloopEvalTrialRow(
            trial_id="valid-parent",
            run_id="run-001",
            case_id="B6-01",
            trial_index=0,
            suite_type="Capability",
            trial_status="valid",
            task_pass=False,
            task_score=0.0,
            failure_reason=None,
            artifact_path="/tmp/evidence.json",
            artifact_sha256="a" * 64,
            created_at="2026-07-28T00:00:00+00:00",
        )
    )
    db_session.flush()
    db_session.add(
        ChatloopEvalViolationRow(
            trial_id="valid-parent",
            policy_id="TRADE-CONFIRM",
            severity="Q",
            triggered_escalations=[],
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_trial_and_violations_roll_back_together_on_constraint_failure(
    db_session: Session,
    tmp_path,
) -> None:
    recorder = ChatloopEvalRecorder(
        session_factory=_session_factory(db_session),
        initialize_schema=False,
    )
    duplicate = Violation(
        policy_id="TRADE-CONFIRM",
        severity="C0",
        triggered_escalations=[],
    )
    record = _record(
        artifact=_artifact(tmp_path, trial_id="trial-rollback"),
        trial_id="trial-rollback",
        status="valid",
        task_pass=False,
        violations=(duplicate, duplicate),
    )

    with pytest.raises(IntegrityError):
        recorder.record_trial(record)

    assert db_session.get(ChatloopEvalTrialRow, "trial-rollback") is None
    assert not db_session.scalars(
        select(ChatloopEvalViolationRow).where(
            ChatloopEvalViolationRow.trial_id == "trial-rollback"
        )
    ).all()
