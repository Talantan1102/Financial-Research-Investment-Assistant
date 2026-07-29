from __future__ import annotations

from eval.chatloop.business_reporting import derive_business_run_summary
from eval.chatloop.case_loader import load_catalog


def test_report_separates_validity_pass_score_and_reliability() -> None:
    catalog = load_catalog()
    trials = [
        _trial("t1", "B1-01", 0, status="valid", passed=True, score=90.0),
        _trial("t2", "B1-01", 1, status="valid", passed=False, score=50.0),
        _trial(
            "t3",
            "B4-01",
            0,
            status="invalid_evidence",
            passed=None,
            score=None,
            failure_reason="missing tool ledger",
        ),
    ]

    report = derive_business_run_summary(
        run={"run_id": "run-1", "mode": "business"},
        trials=trials,
        violations=[],
        catalog=catalog,
        artifacts={trial["trial_id"]: _artifact(trial) for trial in trials},
    )

    assert report["total_trials"] == 3
    assert report["valid_trial_rate"] == 2 / 3
    assert report["task_pass_rate"] == 0.5
    assert report["diagnostic_score"] == 70.0
    assert report["release_eligible"] is False
    assert report["cases"][0] == {
        "case_id": "B1-01",
        "suite_type": "Capability",
        "k": 2,
        "total_trials": 2,
        "valid_trials": 2,
        "pass_at_1": 0.5,
        "pass_power_k": False,
        "complete": True,
    }
    assert report["cases"][1]["pass_power_k"] is None
    assert report["failure_reasons"] == [{"reason": "missing tool ledger", "count": 1}]


def test_report_exposes_policy_review_axes_tasks_and_artifacts() -> None:
    catalog = load_catalog()
    trials = [
        _trial("t1", "B1-01", 0, status="valid", passed=False, score=0.0),
        _trial("t2", "B4-01", 0, status="valid", passed=False, score=10.0),
    ]
    artifacts = {
        "t1": _artifact(
            trials[0],
            flags=[
                {"reason": "judge_uncertain", "assertion_id": "judge-1"},
                {"reason": "judge_uncertain", "assertion_id": "judge-1"},
            ],
        ),
        "t2": _artifact(trials[1]),
    }

    report = derive_business_run_summary(
        run={"run_id": "run-2", "mode": "business"},
        trials=trials,
        violations=[
            {"trial_id": "t1", "policy_id": "POL-C0", "severity": "C0"},
            {"trial_id": "t2", "policy_id": "POL-C1", "severity": "C1"},
            {"trial_id": "t2", "policy_id": "POL-C3", "severity": "C3"},
        ],
        catalog=catalog,
        artifacts=artifacts,
    )

    assert report["violations"] == {"C0": 1, "C1": 1, "C2": 0, "C3": 1}
    assert {item["reason"] for item in report["human_review"]} == {
        "C0",
        "C1",
        "judge_uncertain",
    }
    assert report["environment_coverage"]["E1"] == 2
    assert report["task_groups"]["T1"] == {"total": 1, "valid": 1, "passed": 0}
    assert report["task_groups"]["T5"] == {"total": 1, "valid": 1, "passed": 0}
    assert report["artifact_links"] == [
        {"trial_id": "t1", "case_id": "B1-01", "path": "/artifacts/t1.json"},
        {"trial_id": "t2", "case_id": "B4-01", "path": "/artifacts/t2.json"},
    ]


def test_incomplete_regression_run_cannot_look_complete_or_release_eligible() -> None:
    catalog = load_catalog()
    trial = _trial(
        "t1",
        "B1-01",
        0,
        status="valid",
        passed=True,
        score=100.0,
        suite_type="Regression",
    )

    report = derive_business_run_summary(
        run={
            "run_id": "run-crashed",
            "mode": "business",
            "status": "harness_failed",
            "config_json": {"trial_counts": {"B1-01": 3, "B1-02": 1}},
        },
        trials=[trial],
        violations=[],
        catalog=catalog,
        artifacts={"t1": _artifact(trial)},
    )

    assert report["planned_trials"] == 4
    assert report["recorded_trials"] == 1
    assert report["run_complete"] is False
    assert report["release_eligible"] is False
    assert report["cases"][0] == {
        "case_id": "B1-01",
        "suite_type": "Regression",
        "k": 3,
        "total_trials": 1,
        "valid_trials": 1,
        "pass_at_1": 1.0,
        "pass_power_k": None,
        "complete": False,
    }
    assert report["cases"][1]["case_id"] == "B1-02"
    assert report["cases"][1]["total_trials"] == 0
    assert report["cases"][1]["complete"] is False


def test_composite_task_type_counts_once_in_each_member_group() -> None:
    catalog = load_catalog()
    trial = _trial("t1", "B8-03", 0, status="valid", passed=True, score=100.0)

    report = derive_business_run_summary(
        run={"run_id": "run-composite", "mode": "business"},
        trials=[trial],
        violations=[],
        catalog=catalog,
    )

    assert report["task_groups"]["T3"] == {"total": 1, "valid": 1, "passed": 1}
    assert report["task_groups"]["T5"] == {"total": 1, "valid": 1, "passed": 1}
    assert report["task_groups"]["T7"] == {"total": 1, "valid": 1, "passed": 1}
    assert report["task_groups"]["T1"] == {"total": 0, "valid": 0, "passed": 0}


def _trial(
    trial_id: str,
    case_id: str,
    index: int,
    *,
    status: str,
    passed: bool | None,
    score: float | None,
    failure_reason: str | None = None,
    suite_type: str = "Capability",
) -> dict[str, object]:
    return {
        "trial_id": trial_id,
        "case_id": case_id,
        "trial_index": index,
        "suite_type": suite_type,
        "trial_status": status,
        "task_pass": passed,
        "task_score": score,
        "failure_reason": failure_reason,
        "artifact_path": f"/artifacts/{trial_id}.json",
    }


def _artifact(
    trial: dict[str, object],
    *,
    flags: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "trial_id": trial["trial_id"],
        "case_id": trial["case_id"],
        "evaluation": {"human_review_flags": flags or []},
    }
