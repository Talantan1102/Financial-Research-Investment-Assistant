"""Honest run summaries for the conversational business evaluator."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from statistics import fmean
from typing import Any

from eval.chatloop.case_loader import CaseCatalog

_TASK_GROUP = re.compile(r"T[1-9]")
_SEVERITIES = ("C0", "C1", "C2", "C3")
_REVIEW_SEVERITIES = {"C0", "C1"}


def derive_business_run_summary(
    *,
    run: Mapping[str, Any],
    trials: Sequence[Mapping[str, Any]],
    violations: Sequence[Mapping[str, Any]],
    catalog: CaseCatalog,
    artifacts: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Separate harness validity, task outcomes, scores, and policy review facts."""
    artifact_by_trial = artifacts or {}
    cases = {case.case_id: case for case in catalog.cases}
    config = run.get("config_json")
    config = config if isinstance(config, Mapping) else {}
    raw_trial_counts = config.get("trial_counts")
    raw_trial_counts = raw_trial_counts if isinstance(raw_trial_counts, Mapping) else {}
    planned_by_case = {
        str(case_id): int(count)
        for case_id, count in raw_trial_counts.items()
        if isinstance(count, int) and not isinstance(count, bool) and count > 0
    }
    raw_suite_types = config.get("suite_types")
    raw_suite_types = raw_suite_types if isinstance(raw_suite_types, Mapping) else {}
    trial_by_id = {str(trial["trial_id"]): trial for trial in trials}
    valid = [trial for trial in trials if trial.get("trial_status") == "valid"]
    passes = [trial for trial in valid if trial.get("task_pass") is True]
    scores = [float(trial["task_score"]) for trial in valid if trial.get("task_score") is not None]

    severity_counts: Counter[str] = Counter()
    review_items: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for violation in violations:
        severity = str(violation.get("severity") or "")
        if severity in _SEVERITIES:
            severity_counts[severity] += 1
        if severity in _REVIEW_SEVERITIES:
            trial_id = str(violation.get("trial_id") or "")
            trial = trial_by_id.get(trial_id, {})
            policy_id = str(violation.get("policy_id") or "")
            key = (trial_id, severity, policy_id, policy_id)
            review_items[key] = _review_item(
                trial,
                trial_id=trial_id,
                reason=severity,
                assertion_id=policy_id,
                policy_id=policy_id,
            )

    for trial_id, artifact in artifact_by_trial.items():
        trial = trial_by_id.get(trial_id, {})
        evaluation = artifact.get("evaluation")
        if not isinstance(evaluation, Mapping):
            continue
        flags = evaluation.get("human_review_flags")
        if not isinstance(flags, list):
            continue
        for flag in flags:
            if not isinstance(flag, Mapping):
                continue
            reason = str(flag.get("reason") or "")
            if not reason:
                continue
            assertion_id = str(flag.get("assertion_id") or "")
            policy_id = str(flag.get("policy_id") or "")
            key = (trial_id, reason, assertion_id, policy_id)
            review_items[key] = _review_item(
                trial,
                trial_id=trial_id,
                reason=reason,
                assertion_id=assertion_id,
                policy_id=policy_id or None,
            )

    axes = {f"E{index}": 0 for index in range(1, 15)}
    task_groups = {f"T{index}": {"total": 0, "valid": 0, "passed": 0} for index in range(1, 10)}
    per_case: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for trial in trials:
        case_id = str(trial.get("case_id") or "")
        case = cases.get(case_id)
        if case is None:
            continue
        per_case[case_id].append(trial)
        for axis in case.initial_state.axes:
            axes[axis] += 1
        for task_group in dict.fromkeys(_TASK_GROUP.findall(case.task_type)):
            bucket = task_groups[task_group]
            bucket["total"] += 1
            if trial.get("trial_status") == "valid":
                bucket["valid"] += 1
                if trial.get("task_pass") is True:
                    bucket["passed"] += 1

    observed_suites = {str(trial.get("suite_type") or "") for trial in trials}
    default_suite = next(iter(observed_suites)) if len(observed_suites) == 1 else ""
    all_case_ids = sorted(set(per_case) | set(planned_by_case))
    case_summaries = [
        _case_summary(
            case_id,
            per_case.get(case_id, []),
            expected_k=planned_by_case.get(case_id, len(per_case.get(case_id, []))),
            suite_type=str(
                raw_suite_types.get(case_id)
                or default_suite
                or (cases[case_id].suite_type.value if case_id in cases else "")
            ),
        )
        for case_id in all_case_ids
    ]
    review = list(review_items.values())
    suites = {str(item["suite_type"]) for item in case_summaries}
    planned_trials = sum(planned_by_case.values()) if planned_by_case else len(trials)
    run_complete = (
        bool(planned_trials)
        and len(trials) == planned_trials
        and all(item["complete"] for item in case_summaries)
        and run.get("status") == "completed"
    )
    release_eligible = (
        run_complete
        and suites == {"Regression"}
        and not review
        and all(
            trial.get("trial_status") == "valid" and trial.get("task_pass") is True
            for trial in trials
        )
    )
    failure_counts = Counter(
        str(trial["failure_reason"])
        for trial in trials
        if trial.get("failure_reason") not in {None, ""}
    )

    return {
        "total_trials": len(trials),
        "planned_trials": planned_trials,
        "recorded_trials": len(trials),
        "run_complete": run_complete,
        "valid_trials": len(valid),
        "valid_trial_rate": len(valid) / len(trials) if trials else 0.0,
        "task_passes": len(passes),
        "task_pass_rate": len(passes) / len(valid) if valid else 0.0,
        "diagnostic_score": fmean(scores) if scores else None,
        "release_eligible": release_eligible,
        "violations": {severity: severity_counts[severity] for severity in _SEVERITIES},
        "environment_coverage": axes,
        "task_groups": task_groups,
        "failure_reasons": [
            {"reason": reason, "count": count} for reason, count in sorted(failure_counts.items())
        ],
        "human_review": review,
        "cases": case_summaries,
        "artifact_links": [
            {
                "trial_id": str(trial.get("trial_id") or ""),
                "case_id": str(trial.get("case_id") or ""),
                "path": str(trial.get("artifact_path") or ""),
            }
            for trial in trials
        ],
        # Promotion needs a separately persisted human-review record. Trial flags alone
        # are review requests, not reviewer approval, so this evaluator never auto-promotes.
        "promotion_candidates": [],
    }


def _case_summary(
    case_id: str,
    trials: Sequence[Mapping[str, Any]],
    *,
    expected_k: int,
    suite_type: str,
) -> dict[str, Any]:
    valid = [trial for trial in trials if trial.get("trial_status") == "valid"]
    observed_indexes = {trial.get("trial_index") for trial in trials}
    complete = (
        expected_k > 0
        and len(trials) == expected_k
        and len(valid) == expected_k
        and observed_indexes == set(range(expected_k))
    )
    pass_at_1 = (
        sum(trial.get("task_pass") is True for trial in valid) / len(valid) if valid else 0.0
    )
    return {
        "case_id": case_id,
        "suite_type": suite_type,
        "k": expected_k,
        "total_trials": len(trials),
        "valid_trials": len(valid),
        "pass_at_1": pass_at_1,
        "pass_power_k": (
            all(trial.get("task_pass") is True for trial in valid) if complete else None
        ),
        "complete": complete,
    }


def _review_item(
    trial: Mapping[str, Any],
    *,
    trial_id: str,
    reason: str,
    assertion_id: str,
    policy_id: str | None,
) -> dict[str, Any]:
    return {
        "trial_id": trial_id,
        "case_id": str(trial.get("case_id") or ""),
        "reason": reason,
        "assertion_id": assertion_id,
        "policy_id": policy_id,
        "artifact_path": str(trial.get("artifact_path") or ""),
    }


__all__ = ["derive_business_run_summary"]
