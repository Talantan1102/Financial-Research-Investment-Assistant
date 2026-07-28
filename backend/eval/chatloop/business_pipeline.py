"""Injectable trial scoring, durable evidence, and honest reliability summaries."""

from __future__ import annotations

import asyncio
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any, Protocol, cast

from pydantic import BaseModel

from eval.chatloop.artifact_store import ArtifactReference
from eval.chatloop.business_cli import (
    BusinessCasePlan,
    BusinessTrialOutcome,
)
from eval.chatloop.business_runner import BusinessTrialResult
from eval.chatloop.case_schema import ConversationCase
from eval.chatloop.policy_registry import PolicyRegistry
from eval.chatloop.recorder import TrialRecord
from eval.chatloop.trial_evaluator import (
    TrialEvaluation,
    TrialStatus,
    evaluate_harness_failure,
    evaluate_invalid_evidence,
    evaluate_trial,
)


class StructuredEvidenceProvider(Protocol):
    """Build assertion-ready evidence without pipeline-side semantic inference."""

    async def build(
        self,
        case: ConversationCase,
        result: BusinessTrialResult,
    ) -> Mapping[str, Any]: ...


class InvalidEvidenceError(RuntimeError):
    """The trial ran, but required evidence could not be collected or verified."""


class BusinessTrialRunner(Protocol):
    async def run_trial(
        self,
        case: ConversationCase,
        *,
        trial_index: int,
        random_seed: int = 0,
    ) -> BusinessTrialResult: ...


class TrialArtifactStore(Protocol):
    def write(self, bundle: Mapping[str, Any]) -> ArtifactReference: ...


class TrialRecorder(Protocol):
    def record_trial(self, trial: TrialRecord) -> str: ...


class TrialPersistenceError(RuntimeError):
    """A trial could not be durably persisted, so no outcome may be returned."""

    def __init__(
        self,
        *,
        stage: str,
        trial_id: str,
        case_id: str,
        artifact: ArtifactReference | None = None,
    ) -> None:
        self.stage = stage
        self.trial_id = trial_id
        self.case_id = case_id
        self.artifact = artifact
        super().__init__(f"{stage} persistence failed for {case_id} ({trial_id})")


@dataclass(frozen=True, slots=True)
class BusinessCaseReliability:
    case_id: str
    k: int
    valid_trials: int
    pass1: float
    pass_power_k: bool | None
    complete: bool


class BusinessTrialPipeline:
    """Run, score, write artifact, then record exactly one business trial.

    Artifact and recorder writes cannot share one transaction. The artifact is
    therefore written first and is content-addressed/idempotent. If the recorder
    fails, the artifact remains as an auditable orphan and this method raises;
    it never returns a result that would hide the persistence failure.
    """

    def __init__(
        self,
        *,
        runner: BusinessTrialRunner,
        evidence_provider: StructuredEvidenceProvider,
        policy_registry: PolicyRegistry,
        artifact_store: TrialArtifactStore,
        trial_recorder: TrialRecorder,
        versions: Mapping[str, str],
        policy_as_of: date,
        run_id: str,
    ) -> None:
        self._runner = runner
        self._evidence_provider = evidence_provider
        self._policy_registry = policy_registry
        self._artifact_store = artifact_store
        self._trial_recorder = trial_recorder
        self._versions = dict(versions)
        self._policy_as_of = policy_as_of
        self._run_id = run_id

    async def run_trial(
        self,
        case: ConversationCase,
        *,
        trial_index: int,
        random_seed: int,
    ) -> BusinessTrialOutcome:
        trial_id = _trial_id(self._run_id, case.case_id, trial_index)
        runner_started = time.perf_counter()
        structured_observation: Mapping[str, Any] | None
        failure_provenance: dict[str, str] | None
        try:
            result = await self._runner.run_trial(
                case,
                trial_index=trial_index,
                random_seed=random_seed,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            result = BusinessTrialResult(
                case_id=case.case_id,
                trial_index=trial_index,
                trial_status="harness_failed",
                failure_reason=reason,
                observation=None,
                database_before_after={"before": {}, "after": {}},
                environment_manifest={"runner_exception": reason},
                duration_ms=max(0, int((time.perf_counter() - runner_started) * 1000)),
            )
            evaluation = evaluate_harness_failure(reason)
            structured_observation = None
            failure_provenance = {"stage": "runner_exception", "reason": reason}
        else:
            evaluation, structured_observation, failure_provenance = await self._evaluate(
                case,
                result,
                trial_index=trial_index,
            )
        bundle = self._artifact_bundle(
            case=case,
            result=result,
            evaluation=evaluation,
            structured_observation=structured_observation,
            failure_provenance=failure_provenance,
            trial_id=trial_id,
            trial_index=trial_index,
            random_seed=random_seed,
        )
        try:
            artifact = self._artifact_store.write(bundle)
        except Exception as exc:
            raise TrialPersistenceError(
                stage="artifact",
                trial_id=trial_id,
                case_id=case.case_id,
            ) from exc

        record = TrialRecord(
            trial_id=trial_id,
            run_id=self._run_id,
            case_id=case.case_id,
            trial_index=trial_index,
            suite_type=case.suite_type.value,
            trial_status=evaluation.trial_status.value,
            task_pass=evaluation.task_pass,
            task_score=evaluation.task_score,
            failure_reason=evaluation.failure_reason,
            artifact=artifact,
            violations=evaluation.violations,
        )
        try:
            self._trial_recorder.record_trial(record)
        except Exception as exc:
            raise TrialPersistenceError(
                stage="recorder",
                trial_id=trial_id,
                case_id=case.case_id,
                artifact=artifact,
            ) from exc

        return BusinessTrialOutcome(
            case_id=case.case_id,
            trial_index=trial_index,
            trial_status=cast(Any, evaluation.trial_status.value),
            task_pass=evaluation.task_pass,
        )

    async def _evaluate(
        self,
        case: ConversationCase,
        result: BusinessTrialResult,
        *,
        trial_index: int,
    ) -> tuple[TrialEvaluation, Mapping[str, Any] | None, dict[str, str] | None]:
        identity_error = _runner_identity_error(case, result, trial_index)
        if identity_error is not None:
            return (
                evaluate_harness_failure(identity_error),
                None,
                {"stage": "runner", "reason": identity_error},
            )
        if result.trial_status == "invalid_evidence":
            reason = result.failure_reason or "runner returned invalid_evidence"
            return (
                evaluate_invalid_evidence(reason),
                None,
                {"stage": "runner", "reason": reason},
            )
        if result.trial_status != "valid":
            reason = result.failure_reason or f"runner returned {result.trial_status}"
            return (
                evaluate_harness_failure(reason),
                None,
                {"stage": "runner", "reason": reason},
            )
        if result.observation is None:
            reason = "runner returned valid without an observation"
            return (
                evaluate_harness_failure(reason),
                None,
                {"stage": "runner", "reason": reason},
            )

        try:
            structured_observation = await self._evidence_provider.build(case, result)
            if not isinstance(structured_observation, Mapping):
                raise TypeError("evidence provider must return a mapping")
        except InvalidEvidenceError as exc:
            reason = str(exc) or "incomplete evidence"
            return (
                evaluate_invalid_evidence(reason),
                None,
                {"stage": "evidence_provider", "reason": reason},
            )
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            return (
                evaluate_harness_failure(reason),
                None,
                {"stage": "evidence_provider", "reason": reason},
            )

        try:
            evaluation = evaluate_trial(
                case,
                observation=structured_observation,
                policy_registry=self._policy_registry,
                policy_as_of=self._policy_as_of,
                policy_version=self._versions.get("policy"),
            )
        except Exception as exc:  # noqa: BLE001 - evaluator failures are harness facts
            reason = f"{type(exc).__name__}: {exc}"
            return (
                evaluate_harness_failure(reason),
                structured_observation,
                {"stage": "trial_evaluator_exception", "reason": reason},
            )
        if evaluation.trial_status is TrialStatus.INVALID_EVIDENCE:
            provenance = {
                "stage": "evidence_validation",
                "reason": evaluation.failure_reason or "invalid evidence",
            }
        elif evaluation.trial_status is TrialStatus.HARNESS_FAILED:
            provenance = {
                "stage": "trial_evaluator",
                "reason": evaluation.failure_reason or "trial evaluator failed",
            }
        elif evaluation.task_pass is False:
            provenance = {
                "stage": "agent_assertions",
                "reason": evaluation.failure_reason or "assertions_failed",
            }
        else:
            provenance = None
        return evaluation, structured_observation, provenance

    def _artifact_bundle(
        self,
        *,
        case: ConversationCase,
        result: BusinessTrialResult,
        evaluation: TrialEvaluation,
        structured_observation: Mapping[str, Any] | None,
        failure_provenance: Mapping[str, str] | None,
        trial_id: str,
        trial_index: int,
        random_seed: int,
    ) -> dict[str, Any]:
        raw = result.observation
        return {
            "schema_version": 1,
            "trial_id": trial_id,
            "run_id": self._run_id,
            "case_id": case.case_id,
            "trial_index": trial_index,
            "transcript": [] if raw is None else _jsonable(raw.transcript),
            "tool_ledger": [] if raw is None else _jsonable(raw.tool_ledger),
            "database_before_after": _jsonable(result.database_before_after),
            "versions": dict(self._versions),
            "random_seed": random_seed,
            "reproducibility": {
                "harness_seed": random_seed,
                "harness_seed_scope": "request_identity",
                "model_seed_applied": False,
            },
            "duration_ms": result.duration_ms,
            "cost": {
                "cny": None if raw is None else raw.cost_cny,
                "total_tokens": None if raw is None else raw.total_tokens,
            },
            "structured_observation": _jsonable(structured_observation),
            "evaluation": _jsonable(evaluation),
            "environment_manifest": _jsonable(result.environment_manifest),
            "failure_provenance": _jsonable(failure_provenance),
        }


class BusinessPlanExecutor:
    """Execute plans serially and stop loudly on any persistence failure."""

    def __init__(
        self,
        *,
        runner: BusinessTrialRunner,
        evidence_provider: StructuredEvidenceProvider,
        policy_registry: PolicyRegistry,
        artifact_store: TrialArtifactStore,
        trial_recorder: TrialRecorder,
        versions: Mapping[str, str],
        policy_as_of: date,
        run_id: str,
        base_random_seed: int,
    ) -> None:
        if base_random_seed < 0:
            raise ValueError("base_random_seed must be non-negative")
        self._pipeline = BusinessTrialPipeline(
            runner=runner,
            evidence_provider=evidence_provider,
            policy_registry=policy_registry,
            artifact_store=artifact_store,
            trial_recorder=trial_recorder,
            versions=versions,
            policy_as_of=policy_as_of,
            run_id=run_id,
        )
        self._base_random_seed = base_random_seed

    async def __call__(
        self,
        plans: Sequence[BusinessCasePlan],
    ) -> list[BusinessTrialOutcome]:
        plan_counts = Counter(plan.case.case_id for plan in plans)
        duplicate_case_ids = sorted(case_id for case_id, count in plan_counts.items() if count > 1)
        if duplicate_case_ids:
            raise ValueError(f"duplicate case plan: {', '.join(duplicate_case_ids)}")

        outcomes: list[BusinessTrialOutcome] = []
        ordinal = 0
        for plan in plans:
            for trial_index in range(plan.trial_count):
                outcomes.append(
                    await self._pipeline.run_trial(
                        plan.case,
                        trial_index=trial_index,
                        random_seed=self._base_random_seed + ordinal,
                    )
                )
                ordinal += 1
        return outcomes


def summarize_case_reliability(
    plans: Sequence[BusinessCasePlan],
    outcomes: Sequence[BusinessTrialOutcome],
) -> tuple[BusinessCaseReliability, ...]:
    """Summarize valid trials without converting invalid trials into Agent failures."""
    plan_ids = [plan.case.case_id for plan in plans]
    if len(set(plan_ids)) != len(plan_ids):
        raise ValueError("reliability plans require unique case IDs")
    unknown_case_ids = {item.case_id for item in outcomes}.difference(plan_ids)
    if unknown_case_ids:
        raise ValueError(f"outcomes contain unknown case IDs: {sorted(unknown_case_ids)}")

    summaries: list[BusinessCaseReliability] = []
    for plan in plans:
        case_outcomes = [item for item in outcomes if item.case_id == plan.case.case_id]
        expected_indices = Counter(range(plan.trial_count))
        actual_indices = Counter(item.trial_index for item in case_outcomes)
        valid = [item for item in case_outcomes if item.trial_status == "valid"]
        pass1 = sum(item.task_pass is True for item in valid) / len(valid) if valid else 0.0
        complete = (
            actual_indices == expected_indices
            and len(valid) == plan.trial_count
            and all(isinstance(item.task_pass, bool) for item in valid)
        )
        summaries.append(
            BusinessCaseReliability(
                case_id=plan.case.case_id,
                k=plan.trial_count,
                valid_trials=len(valid),
                pass1=pass1,
                pass_power_k=(all(item.task_pass is True for item in valid) if complete else None),
                complete=complete,
            )
        )
    return tuple(summaries)


def _runner_identity_error(
    case: ConversationCase,
    result: BusinessTrialResult,
    trial_index: int,
) -> str | None:
    if result.case_id != case.case_id or result.trial_index != trial_index:
        return (
            "runner returned mismatched identity: "
            f"{result.case_id}/{result.trial_index} != {case.case_id}/{trial_index}"
        )
    return None


def _trial_id(run_id: str, case_id: str, trial_index: int) -> str:
    return f"{run_id}.{case_id}.{trial_index}"


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _jsonable(getattr(value, field.name)) for field in fields(value)}
    raise TypeError(f"value is not JSON-compatible: {type(value).__name__}")


__all__ = [
    "BusinessCaseReliability",
    "BusinessPlanExecutor",
    "BusinessTrialPipeline",
    "InvalidEvidenceError",
    "StructuredEvidenceProvider",
    "TrialPersistenceError",
    "summarize_case_reliability",
]
