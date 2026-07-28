"""Trial validity, task-pass, scoring, and batch-summary semantics."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from statistics import fmean
from typing import Any, cast

from eval.chatloop.assertion_engine import AssertionEngine, AssertionResult, AssertionResultKind
from eval.chatloop.case_schema import AcceptableOutcome, AssertionSpec, ConversationCase
from eval.chatloop.policy_registry import PolicyRegistry, Severity, Violation

__all__ = [
    "AcceptableOutcomeResult",
    "BatchSummary",
    "HumanReviewFlag",
    "TrialEvaluation",
    "TrialStatus",
    "evaluate_harness_failure",
    "evaluate_trial",
    "summarize_batch",
    "task_pass",
]


class TrialStatus(StrEnum):
    VALID = "valid"
    HARNESS_FAILED = "harness_failed"
    INVALID_EVIDENCE = "invalid_evidence"


@dataclass(frozen=True, slots=True)
class HumanReviewFlag:
    reason: str
    assertion_id: str
    policy_id: str | None = None
    severity: str | None = None


@dataclass(frozen=True, slots=True)
class AcceptableOutcomeResult:
    name_zh: str
    assertion_results: tuple[AssertionResult, ...]
    passed: bool
    kind: AssertionResultKind


@dataclass(frozen=True, slots=True)
class TrialEvaluation:
    trial_status: TrialStatus
    task_pass: bool | None
    task_score: float | None
    raw_score: float | None
    failure_reason: str | None
    required_results: tuple[AssertionResult, ...]
    forbidden_results: tuple[AssertionResult, ...]
    expected_state_change_results: tuple[AssertionResult, ...]
    acceptable_outcome_results: tuple[AcceptableOutcomeResult, ...]
    selected_acceptable_outcome: str | None
    violations: tuple[Violation, ...]
    human_review_flags: tuple[HumanReviewFlag, ...]


@dataclass(frozen=True, slots=True)
class BatchSummary:
    total_trials: int
    valid_trial_rate: float
    task_pass_rate: float
    release_eligible: bool
    mean_task_score: float | None


def task_pass(required: Sequence[AssertionResult], trial_status: TrialStatus) -> bool | None:
    if trial_status is not TrialStatus.VALID:
        return None
    return all(item.passed for item in required)


def evaluate_harness_failure(reason: str) -> TrialEvaluation:
    return TrialEvaluation(
        trial_status=TrialStatus.HARNESS_FAILED,
        task_pass=None,
        task_score=None,
        raw_score=None,
        failure_reason=reason,
        required_results=(),
        forbidden_results=(),
        expected_state_change_results=(),
        acceptable_outcome_results=(),
        selected_acceptable_outcome=None,
        violations=(),
        human_review_flags=(),
    )


def evaluate_trial(
    case: ConversationCase,
    *,
    observation: Mapping[str, Any],
    policy_registry: PolicyRegistry,
    policy_as_of: date,
    policy_version: str | None = None,
    q_deductions: float = 0.0,
    harness_failure_reason: str | None = None,
    assertion_engine: AssertionEngine | None = None,
) -> TrialEvaluation:
    engine = assertion_engine or AssertionEngine()

    required_results = _evaluate_group(engine, case.required_assertions, observation)
    forbidden_results = _evaluate_group(engine, case.forbidden_outcomes, observation)
    expected_results = _evaluate_group(engine, case.expected_state_changes, observation)
    acceptable_results = tuple(
        _evaluate_acceptable_outcome(engine, outcome, observation)
        for outcome in case.acceptable_outcomes
    )

    if _has_invalid_evidence(
        required_results, forbidden_results, expected_results, acceptable_results
    ):
        return TrialEvaluation(
            trial_status=TrialStatus.INVALID_EVIDENCE,
            task_pass=None,
            task_score=None,
            raw_score=None,
            failure_reason="incomplete_required_evidence",
            required_results=required_results,
            forbidden_results=forbidden_results,
            expected_state_change_results=expected_results,
            acceptable_outcome_results=acceptable_results,
            selected_acceptable_outcome=None,
            violations=(),
            human_review_flags=_human_review_flags(
                required_results,
                forbidden_results,
                expected_results,
                acceptable_results,
                (),
            ),
        )

    missing_required_evidence = _missing_required_evidence(case, observation)
    if missing_required_evidence:
        return TrialEvaluation(
            trial_status=TrialStatus.INVALID_EVIDENCE,
            task_pass=None,
            task_score=None,
            raw_score=None,
            failure_reason="incomplete_required_evidence",
            required_results=required_results,
            forbidden_results=forbidden_results,
            expected_state_change_results=expected_results,
            acceptable_outcome_results=acceptable_results,
            selected_acceptable_outcome=None,
            violations=(),
            human_review_flags=_human_review_flags(
                required_results,
                forbidden_results,
                expected_results,
                acceptable_results,
                (),
            ),
        )

    if harness_failure_reason is not None:
        return TrialEvaluation(
            trial_status=TrialStatus.HARNESS_FAILED,
            task_pass=None,
            task_score=None,
            raw_score=None,
            failure_reason=harness_failure_reason,
            required_results=required_results,
            forbidden_results=forbidden_results,
            expected_state_change_results=expected_results,
            acceptable_outcome_results=acceptable_results,
            selected_acceptable_outcome=None,
            violations=(),
            human_review_flags=_human_review_flags(
                required_results,
                forbidden_results,
                expected_results,
                acceptable_results,
                (),
            ),
        )

    selected_acceptable_outcome = next(
        (result.name_zh for result in acceptable_results if result.passed),
        None,
    )
    acceptable_pass = selected_acceptable_outcome is not None or not acceptable_results
    mandatory_pass = (
        all(result.passed for result in required_results)
        and not any(result.passed for result in forbidden_results)
        and all(result.passed for result in expected_results)
        and acceptable_pass
    )

    all_results = _flatten_results(
        required_results,
        forbidden_results,
        expected_results,
        acceptable_results,
    )
    raw_score = _raw_score(case.partial_credit, all_results)
    violations = tuple(
        _build_violations(required_results, forbidden_results, expected_results, acceptable_results)
    )
    task_score = policy_registry.apply_caps(
        raw_score=raw_score,
        q_deductions=q_deductions,
        violations=violations,
        as_of=policy_as_of,
        version=policy_version,
    )

    return TrialEvaluation(
        trial_status=TrialStatus.VALID,
        task_pass=mandatory_pass,
        task_score=task_score,
        raw_score=raw_score,
        failure_reason=None if mandatory_pass else "assertions_failed",
        required_results=required_results,
        forbidden_results=forbidden_results,
        expected_state_change_results=expected_results,
        acceptable_outcome_results=acceptable_results,
        selected_acceptable_outcome=selected_acceptable_outcome,
        violations=violations,
        human_review_flags=_human_review_flags(
            required_results,
            forbidden_results,
            expected_results,
            acceptable_results,
            violations,
        ),
    )


def summarize_batch(trials: Sequence[TrialEvaluation]) -> BatchSummary:
    total_trials = len(trials)
    valid_trials = [trial for trial in trials if trial.trial_status is TrialStatus.VALID]
    valid_trial_rate = len(valid_trials) / total_trials if total_trials else 0.0
    task_pass_rate = (
        sum(1 for trial in valid_trials if trial.task_pass is True) / len(valid_trials)
        if valid_trials
        else 0.0
    )
    scores = [trial.task_score for trial in valid_trials if trial.task_score is not None]
    return BatchSummary(
        total_trials=total_trials,
        valid_trial_rate=valid_trial_rate,
        task_pass_rate=task_pass_rate,
        release_eligible=total_trials > 0
        and all(trial.trial_status is TrialStatus.VALID for trial in trials),
        mean_task_score=fmean(scores) if scores else None,
    )


def _evaluate_group(
    engine: AssertionEngine,
    assertions: Sequence[AssertionSpec],
    observation: Mapping[str, Any],
) -> tuple[AssertionResult, ...]:
    return tuple(engine.evaluate(assertion, observation=observation) for assertion in assertions)


def _evaluate_acceptable_outcome(
    engine: AssertionEngine,
    outcome: AcceptableOutcome,
    observation: Mapping[str, Any],
) -> AcceptableOutcomeResult:
    results = tuple(
        engine.evaluate(assertion, observation=observation) for assertion in outcome.assertions
    )
    if any(result.kind is AssertionResultKind.INVALID_EVIDENCE for result in results):
        kind = AssertionResultKind.INVALID_EVIDENCE
    elif all(result.passed for result in results):
        kind = AssertionResultKind.PASSED
    else:
        kind = AssertionResultKind.ASSERTION_FAILED
    return AcceptableOutcomeResult(
        name_zh=outcome.name_zh,
        assertion_results=results,
        passed=all(result.passed for result in results),
        kind=kind,
    )


def _has_invalid_evidence(
    required_results: Sequence[AssertionResult],
    forbidden_results: Sequence[AssertionResult],
    expected_results: Sequence[AssertionResult],
    acceptable_results: Sequence[AcceptableOutcomeResult],
) -> bool:
    mandatory_results = [*required_results, *forbidden_results, *expected_results]
    if any(result.kind is AssertionResultKind.INVALID_EVIDENCE for result in mandatory_results):
        return True
    if acceptable_results and not any(result.passed for result in acceptable_results):
        return all(
            result.kind is AssertionResultKind.INVALID_EVIDENCE for result in acceptable_results
        )
    return False


def _missing_required_evidence(case: ConversationCase, observation: Mapping[str, Any]) -> list[str]:
    missing: list[str] = []
    if case.evidence.transcript and not (
        isinstance(observation.get("run"), Mapping) and "transcript" in observation["run"]
    ):
        missing.append("transcript")
    if case.evidence.tool_ledger and "tools" not in observation:
        missing.append("tool_ledger")
    if case.evidence.database_before_after and not (
        isinstance(observation.get("database"), Mapping)
        and "before" in observation["database"]
        and "after" in observation["database"]
    ):
        missing.append("database_before_after")
    if case.evidence.versions and not (
        isinstance(observation.get("evidence"), Mapping) and "versions" in observation["evidence"]
    ):
        missing.append("versions")
    if case.evidence.cost_latency and not (
        isinstance(observation.get("evidence"), Mapping)
        and "cost_latency" in observation["evidence"]
    ):
        missing.append("cost_latency")
    return missing


def _flatten_results(
    required_results: Sequence[AssertionResult],
    forbidden_results: Sequence[AssertionResult],
    expected_results: Sequence[AssertionResult],
    acceptable_results: Sequence[AcceptableOutcomeResult],
) -> dict[str, AssertionResult]:
    flattened: dict[str, AssertionResult] = {}
    for result in [*required_results, *forbidden_results, *expected_results]:
        flattened[result.assertion_id] = result
    for outcome_result in acceptable_results:
        for result in outcome_result.assertion_results:
            flattened[result.assertion_id] = result
    return flattened


def _raw_score(
    partial_credit: Sequence[Any],
    all_results: Mapping[str, AssertionResult],
) -> float:
    total = 0
    for component in partial_credit:
        assertion_ids = tuple(component.assertion_ids)
        if all(all_results[assertion_id].passed for assertion_id in assertion_ids):
            total += component.points
    return max(0.0, min(100.0, float(total)))


def _build_violations(
    required_results: Sequence[AssertionResult],
    forbidden_results: Sequence[AssertionResult],
    expected_results: Sequence[AssertionResult],
    acceptable_results: Sequence[AcceptableOutcomeResult],
) -> Iterable[Violation]:
    for result in [*required_results, *expected_results]:
        if result.policy_id and result.severity in {"C0", "C1", "C2", "C3"} and not result.passed:
            yield Violation(
                policy_id=result.policy_id,
                severity=cast(Severity, result.severity),
            )
    for result in forbidden_results:
        if result.policy_id and result.severity in {"C0", "C1", "C2", "C3"} and result.passed:
            yield Violation(
                policy_id=result.policy_id,
                severity=cast(Severity, result.severity),
            )
    for outcome_result in acceptable_results:
        if outcome_result.passed:
            continue
        for result in outcome_result.assertion_results:
            if (
                result.policy_id
                and result.severity in {"C0", "C1", "C2", "C3"}
                and not result.passed
            ):
                yield Violation(
                    policy_id=result.policy_id,
                    severity=cast(Severity, result.severity),
                )


def _human_review_flags(
    required_results: Sequence[AssertionResult],
    forbidden_results: Sequence[AssertionResult],
    expected_results: Sequence[AssertionResult],
    acceptable_results: Sequence[AcceptableOutcomeResult],
    violations: Sequence[Violation],
) -> tuple[HumanReviewFlag, ...]:
    flags: dict[tuple[str, str, str | None], HumanReviewFlag] = {}
    for violation in violations:
        if violation.severity in {"C0", "C1"}:
            key = (violation.severity, violation.policy_id, None)
            flags[key] = HumanReviewFlag(
                reason=violation.severity,
                assertion_id=violation.policy_id,
                policy_id=violation.policy_id,
                severity=violation.severity,
            )
    for result in _iter_all_results(
        required_results,
        forbidden_results,
        expected_results,
        acceptable_results,
    ):
        if result.source != "judge" or not isinstance(result.actual, str):
            continue
        if result.actual in {"uncertain", "无法判断"}:
            flags[("judge_uncertain", result.assertion_id, None)] = HumanReviewFlag(
                reason="judge_uncertain",
                assertion_id=result.assertion_id,
            )
        if result.actual in {"conflict", "judge_conflict"}:
            flags[("judge_conflict", result.assertion_id, None)] = HumanReviewFlag(
                reason="judge_conflict",
                assertion_id=result.assertion_id,
            )
    return tuple(flags.values())


def _iter_all_results(
    required_results: Sequence[AssertionResult],
    forbidden_results: Sequence[AssertionResult],
    expected_results: Sequence[AssertionResult],
    acceptable_results: Sequence[AcceptableOutcomeResult],
) -> Iterable[AssertionResult]:
    yield from required_results
    yield from forbidden_results
    yield from expected_results
    for outcome_result in acceptable_results:
        yield from outcome_result.assertion_results
