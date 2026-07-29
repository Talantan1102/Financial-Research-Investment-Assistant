"""Honest trial evaluation, evidence persistence, and reliability summaries."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from eval.chatloop.artifact_store import (
    ArtifactReference,
    ArtifactStore,
    read_verified_artifact,
)
from eval.chatloop.business_cli import BusinessCasePlan, BusinessTrialOutcome
from eval.chatloop.business_pipeline import (
    BusinessPlanExecutor,
    InvalidEvidenceError,
    TrialPersistenceError,
    summarize_case_reliability,
)
from eval.chatloop.business_runner import (
    BusinessObservation,
    BusinessTrialResult,
)
from eval.chatloop.case_schema import (
    AssertionSpec,
    ConversationCase,
    EnvironmentInput,
    EvidenceRequirements,
    ScoreComponent,
    SuiteType,
)
from eval.chatloop.policy_registry import PolicyRegistry
from eval.chatloop.recorder import TrialRecord

VERSIONS = {
    "case": "catalog-v1",
    "policy": "2026.1",
    "evaluator": "business-pipeline-v1",
    "model": "fake-model",
    "prompt_sha256": "a" * 64,
    "git_sha": "a7b4ea93",
}


def make_case(
    case_id: str = "B1-01",
    *,
    expected_answer: str = "ok",
    policy_assertion: bool = False,
) -> ConversationCase:
    assertion = AssertionSpec(
        assertion_id="required-answer",
        source="answer",
        operator="equals",
        path="text",
        expected=expected_answer,
        policy_id="TRADE-SESSION" if policy_assertion else None,
        severity="C0" if policy_assertion else None,
        escalation_rule_ids=["TRADING-WRONG-EXECUTION"] if policy_assertion else [],
    )
    return ConversationCase.model_construct(
        schema_version=1,
        case_id=case_id,
        title_zh="pipeline test",
        task_type="T1",
        suite_type=SuiteType.CAPABILITY,
        risk_level="test",
        user_goal="test",
        user_messages=["test"],
        initial_state=EnvironmentInput.model_construct(
            execution_mode="direct",
            actors={},
            axes={},
            business_state={},
        ),
        hidden_facts={},
        available_tools=[],
        fault_injection=[],
        applicable_policies=[],
        acceptable_outcomes=[],
        required_assertions=[assertion],
        forbidden_outcomes=[],
        expected_state_changes=[],
        answer_requirements=[],
        allowed_variations=[],
        graders=[],
        partial_credit=[
            ScoreComponent(name_zh="complete", points=100, assertion_ids=[]),
        ],
        violation_caps={},
        trial_count=1,
        trial_status=None,
        task_pass=None,
        task_score=None,
        failure_reason=None,
        evidence=EvidenceRequirements(
            transcript=True,
            tool_ledger=True,
            database_before_after=True,
            versions=True,
            cost_latency=True,
        ),
    )


def make_runner_result(
    case_id: str = "B1-01",
    trial_index: int = 0,
    *,
    status: str = "valid",
    failure_reason: str | None = None,
) -> BusinessTrialResult:
    observation = BusinessObservation(
        transcript=(
            {"role": "user", "content": "test"},
            {"role": "assistant", "content": "ok"},
        ),
        tool_ledger=(
            {
                "tool_name": "get_quote",
                "arguments": {"symbol": "600519"},
                "result": {"price": 100},
                "error": None,
                "idempotency_key": "call-1",
            },
        ),
        run_state={"status": "completed"},
        evidence={"raw": "collector output"},
        cost_cny=0.2,
        total_tokens=42,
    )
    return BusinessTrialResult(
        case_id=case_id,
        trial_index=trial_index,
        trial_status=status,  # type: ignore[arg-type]
        failure_reason=failure_reason,
        observation=observation if status == "valid" else None,
        database_before_after={"before": {"orders": 0}, "after": {"orders": 0}},
        environment_manifest={"database": "isolated", "trial": trial_index},
        duration_ms=25,
    )


def complete_structured_observation(answer: str = "ok") -> dict[str, Any]:
    return {
        "run": {"transcript": [{"role": "assistant", "content": answer}]},
        "tools": {"calls": [{"name": "get_quote"}]},
        "database": {"before": {"orders": 0}, "after": {"orders": 0}},
        "answer": {"text": answer},
        "evidence": {
            "versions": dict(VERSIONS),
            "cost_latency": {"cost_cny": 0.2, "duration_ms": 25},
        },
        "judge": {},
    }


class FakeRunner:
    def __init__(self, results: Mapping[tuple[str, int], BusinessTrialResult]) -> None:
        self.results = dict(results)
        self.calls: list[tuple[str, int, int]] = []

    async def run_trial(
        self,
        case: ConversationCase,
        *,
        trial_index: int,
        random_seed: int = 0,
    ) -> BusinessTrialResult:
        self.calls.append((case.case_id, trial_index, random_seed))
        return self.results[(case.case_id, trial_index)]


class RaisingRunner:
    def __init__(self, error: BaseException) -> None:
        self.error = error
        self.calls: list[tuple[str, int, int]] = []

    async def run_trial(
        self,
        case: ConversationCase,
        *,
        trial_index: int,
        random_seed: int = 0,
    ) -> BusinessTrialResult:
        self.calls.append((case.case_id, trial_index, random_seed))
        raise self.error


class FakeEvidenceProvider:
    def __init__(
        self,
        observations: Mapping[str, Mapping[str, Any]] | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.observations = dict(observations or {})
        self.error = error
        self.calls: list[tuple[str, int]] = []

    async def build(
        self,
        case: ConversationCase,
        result: BusinessTrialResult,
    ) -> Mapping[str, Any]:
        self.calls.append((case.case_id, result.trial_index))
        if self.error is not None:
            raise self.error
        return self.observations.get(case.case_id, complete_structured_observation())


class FakeRecorder:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.records: list[TrialRecord] = []

    def record_trial(self, trial: TrialRecord) -> str:
        if self.error is not None:
            raise self.error
        self.records.append(trial)
        return trial.trial_id


class FailingArtifactStore:
    def write(self, bundle: Mapping[str, Any]) -> ArtifactReference:
        raise OSError("artifact disk unavailable")


def make_executor(
    tmp_path: Path,
    *,
    runner: FakeRunner | RaisingRunner,
    provider: FakeEvidenceProvider,
    recorder: FakeRecorder,
    artifact_store: ArtifactStore | FailingArtifactStore | None = None,
    base_random_seed: int = 1000,
) -> BusinessPlanExecutor:
    return BusinessPlanExecutor(
        runner=runner,
        evidence_provider=provider,
        policy_registry=PolicyRegistry.default(),
        artifact_store=artifact_store or ArtifactStore(tmp_path / "artifacts"),
        trial_recorder=recorder,
        versions=VERSIONS,
        policy_as_of=date(2026, 7, 27),
        run_id="run-pipeline-1",
        base_random_seed=base_random_seed,
    )


@pytest.mark.asyncio
async def test_positive_trial_writes_complete_artifact_then_records_outcome(tmp_path: Path) -> None:
    case = make_case()
    runner = FakeRunner({(case.case_id, 0): make_runner_result()})
    provider = FakeEvidenceProvider()
    recorder = FakeRecorder()
    executor = make_executor(tmp_path, runner=runner, provider=provider, recorder=recorder)

    outcomes = await executor([BusinessCasePlan(case=case, trial_count=1)])

    assert outcomes == [BusinessTrialOutcome("B1-01", 0, "valid", True)]
    assert len(recorder.records) == 1
    record = recorder.records[0]
    artifact = read_verified_artifact(record.artifact)
    assert artifact["trial_id"] == record.trial_id
    assert artifact["transcript"][1]["content"] == "ok"
    assert artifact["tool_ledger"][0]["tool_name"] == "get_quote"
    assert artifact["database_before_after"] == {
        "before": {"orders": 0},
        "after": {"orders": 0},
    }
    assert artifact["versions"] == VERSIONS
    assert artifact["random_seed"] == 1000
    assert artifact["reproducibility"] == {
        "harness_seed": 1000,
        "harness_seed_scope": "request_identity",
        "model_seed_applied": False,
    }
    assert artifact["duration_ms"] == 25
    assert artifact["cost"] == {"cny": 0.2, "total_tokens": 42}
    assert artifact["structured_observation"]["answer"]["text"] == "ok"
    assert artifact["evaluation"]["trial_status"] == "valid"
    assert artifact["environment_manifest"]["database"] == "isolated"
    assert artifact["failure_provenance"] is None


@pytest.mark.asyncio
async def test_mandatory_assertion_failure_is_valid_agent_failure(tmp_path: Path) -> None:
    case = make_case(expected_answer="must explain risk")
    runner = FakeRunner({(case.case_id, 0): make_runner_result()})
    recorder = FakeRecorder()
    executor = make_executor(
        tmp_path,
        runner=runner,
        provider=FakeEvidenceProvider(),
        recorder=recorder,
    )

    outcomes = await executor([BusinessCasePlan(case=case, trial_count=1)])

    assert outcomes[0].trial_status == "valid"
    assert outcomes[0].task_pass is False
    assert recorder.records[0].failure_reason == "assertions_failed"
    artifact = read_verified_artifact(recorder.records[0].artifact)
    assert artifact["failure_provenance"] == {
        "stage": "agent_assertions",
        "reason": "assertions_failed",
    }


@pytest.mark.asyncio
async def test_missing_provider_evidence_is_recorded_as_invalid_evidence(tmp_path: Path) -> None:
    case = make_case()
    structured = complete_structured_observation()
    structured.pop("answer")
    runner = FakeRunner({(case.case_id, 0): make_runner_result()})
    recorder = FakeRecorder()
    executor = make_executor(
        tmp_path,
        runner=runner,
        provider=FakeEvidenceProvider({case.case_id: structured}),
        recorder=recorder,
    )

    outcomes = await executor([BusinessCasePlan(case=case, trial_count=1)])

    assert outcomes[0] == BusinessTrialOutcome("B1-01", 0, "invalid_evidence", None)
    artifact = read_verified_artifact(recorder.records[0].artifact)
    assert artifact["evaluation"]["failure_reason"] == "incomplete_required_evidence"
    assert artifact["structured_observation"] == structured


@pytest.mark.asyncio
async def test_runner_harness_failure_skips_provider_but_persists_trial(tmp_path: Path) -> None:
    case = make_case()
    runner = FakeRunner(
        {
            (case.case_id, 0): make_runner_result(
                status="harness_failed",
                failure_reason="environment setup failed",
            )
        }
    )
    provider = FakeEvidenceProvider()
    recorder = FakeRecorder()
    executor = make_executor(tmp_path, runner=runner, provider=provider, recorder=recorder)

    outcomes = await executor([BusinessCasePlan(case=case, trial_count=1)])

    assert outcomes[0] == BusinessTrialOutcome("B1-01", 0, "harness_failed", None)
    assert provider.calls == []
    artifact = read_verified_artifact(recorder.records[0].artifact)
    assert artifact["transcript"] == []
    assert artifact["tool_ledger"] == []
    assert artifact["structured_observation"] is None
    assert artifact["failure_provenance"] == {
        "stage": "runner",
        "reason": "environment setup failed",
    }


@pytest.mark.asyncio
async def test_runner_invalid_evidence_status_and_reason_are_preserved(tmp_path: Path) -> None:
    case = make_case()
    runner = FakeRunner(
        {
            (case.case_id, 0): make_runner_result(
                status="invalid_evidence",
                failure_reason="collector omitted the orders path",
            )
        }
    )
    provider = FakeEvidenceProvider()
    recorder = FakeRecorder()
    executor = make_executor(tmp_path, runner=runner, provider=provider, recorder=recorder)

    outcomes = await executor([BusinessCasePlan(case=case, trial_count=1)])

    assert outcomes == [BusinessTrialOutcome("B1-01", 0, "invalid_evidence", None)]
    assert provider.calls == []
    record = recorder.records[0]
    assert record.trial_status == "invalid_evidence"
    assert record.failure_reason == "collector omitted the orders path"
    artifact = read_verified_artifact(record.artifact)
    assert artifact["evaluation"]["trial_status"] == "invalid_evidence"
    assert artifact["evaluation"]["failure_reason"] == "collector omitted the orders path"
    assert artifact["failure_provenance"] == {
        "stage": "runner",
        "reason": "collector omitted the orders path",
    }


@pytest.mark.asyncio
async def test_runner_exception_becomes_complete_persisted_harness_failure(
    tmp_path: Path,
) -> None:
    case = make_case()
    runner = RaisingRunner(RuntimeError("prepare failed"))
    provider = FakeEvidenceProvider()
    recorder = FakeRecorder()
    executor = make_executor(tmp_path, runner=runner, provider=provider, recorder=recorder)

    outcomes = await executor([BusinessCasePlan(case=case, trial_count=1)])

    assert outcomes == [BusinessTrialOutcome("B1-01", 0, "harness_failed", None)]
    assert provider.calls == []
    artifact = read_verified_artifact(recorder.records[0].artifact)
    assert artifact["transcript"] == []
    assert artifact["tool_ledger"] == []
    assert artifact["database_before_after"] == {"before": {}, "after": {}}
    assert artifact["environment_manifest"] == {
        "runner_exception": "RuntimeError: prepare failed",
    }
    assert artifact["failure_provenance"] == {
        "stage": "runner_exception",
        "reason": "RuntimeError: prepare failed",
    }
    assert artifact["evaluation"]["trial_status"] == "harness_failed"


@pytest.mark.asyncio
async def test_runner_cancellation_propagates_without_persisting_a_trial(tmp_path: Path) -> None:
    case = make_case()
    runner = RaisingRunner(asyncio.CancelledError())
    provider = FakeEvidenceProvider()
    recorder = FakeRecorder()
    root = tmp_path / "artifacts"
    executor = make_executor(
        tmp_path,
        runner=runner,
        provider=provider,
        recorder=recorder,
        artifact_store=ArtifactStore(root),
    )

    with pytest.raises(asyncio.CancelledError):
        await executor([BusinessCasePlan(case=case, trial_count=1)])

    assert provider.calls == []
    assert recorder.records == []
    assert list(root.rglob("*.json")) == []


@pytest.mark.asyncio
async def test_provider_exception_becomes_persisted_harness_failure(tmp_path: Path) -> None:
    case = make_case()
    runner = FakeRunner({(case.case_id, 0): make_runner_result()})
    provider = FakeEvidenceProvider(error=RuntimeError("collector exploded"))
    recorder = FakeRecorder()
    executor = make_executor(tmp_path, runner=runner, provider=provider, recorder=recorder)

    outcomes = await executor([BusinessCasePlan(case=case, trial_count=1)])

    assert outcomes[0].trial_status == "harness_failed"
    assert outcomes[0].task_pass is None
    artifact = read_verified_artifact(recorder.records[0].artifact)
    assert artifact["failure_provenance"] == {
        "stage": "evidence_provider",
        "reason": "RuntimeError: collector exploded",
    }
    assert artifact["evaluation"]["failure_reason"] == "RuntimeError: collector exploded"


@pytest.mark.asyncio
async def test_provider_declared_incomplete_evidence_is_not_harness_failure(tmp_path: Path) -> None:
    case = make_case()
    runner = FakeRunner({(case.case_id, 0): make_runner_result()})
    provider = FakeEvidenceProvider(error=InvalidEvidenceError("missing tool result payload"))
    recorder = FakeRecorder()
    executor = make_executor(tmp_path, runner=runner, provider=provider, recorder=recorder)

    outcomes = await executor([BusinessCasePlan(case=case, trial_count=1)])

    assert outcomes == [BusinessTrialOutcome("B1-01", 0, "invalid_evidence", None)]
    artifact = read_verified_artifact(recorder.records[0].artifact)
    assert artifact["failure_provenance"] == {
        "stage": "evidence_provider",
        "reason": "missing tool result payload",
    }


@pytest.mark.asyncio
async def test_evaluator_exception_becomes_persisted_harness_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = make_case()
    runner = FakeRunner({(case.case_id, 0): make_runner_result()})
    recorder = FakeRecorder()
    executor = make_executor(
        tmp_path,
        runner=runner,
        provider=FakeEvidenceProvider(),
        recorder=recorder,
    )

    def explode(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise RuntimeError("evaluator exploded")

    monkeypatch.setattr("eval.chatloop.business_pipeline.evaluate_trial", explode)

    outcomes = await executor([BusinessCasePlan(case=case, trial_count=1)])

    assert outcomes == [BusinessTrialOutcome("B1-01", 0, "harness_failed", None)]
    artifact = read_verified_artifact(recorder.records[0].artifact)
    assert artifact["structured_observation"] == complete_structured_observation()
    assert artifact["failure_provenance"] == {
        "stage": "trial_evaluator_exception",
        "reason": "RuntimeError: evaluator exploded",
    }
    assert artifact["evaluation"]["failure_reason"] == "RuntimeError: evaluator exploded"


@pytest.mark.asyncio
async def test_artifact_failure_aborts_before_recorder_and_returns_no_fake_outcome(
    tmp_path: Path,
) -> None:
    case = make_case()
    runner = FakeRunner({(case.case_id, 0): make_runner_result()})
    recorder = FakeRecorder()
    executor = make_executor(
        tmp_path,
        runner=runner,
        provider=FakeEvidenceProvider(),
        recorder=recorder,
        artifact_store=FailingArtifactStore(),
    )

    with pytest.raises(TrialPersistenceError, match="artifact.*B1-01"):
        await executor([BusinessCasePlan(case=case, trial_count=1)])

    assert recorder.records == []


@pytest.mark.asyncio
async def test_recorder_failure_aborts_executor_and_leaves_auditable_artifact(
    tmp_path: Path,
) -> None:
    case = make_case()
    runner = FakeRunner({(case.case_id, 0): make_runner_result()})
    recorder = FakeRecorder(error=RuntimeError("database unavailable"))
    root = tmp_path / "artifacts"
    executor = make_executor(
        tmp_path,
        runner=runner,
        provider=FakeEvidenceProvider(),
        recorder=recorder,
        artifact_store=ArtifactStore(root),
    )

    with pytest.raises(TrialPersistenceError, match="recorder.*B1-01"):
        await executor([BusinessCasePlan(case=case, trial_count=1)])

    assert len(list(root.rglob("*.json"))) == 1


@pytest.mark.asyncio
async def test_c0_violation_caps_score_and_is_fully_recorded(tmp_path: Path) -> None:
    case = make_case(expected_answer="blocked", policy_assertion=True)
    runner = FakeRunner({(case.case_id, 0): make_runner_result()})
    recorder = FakeRecorder()
    executor = make_executor(
        tmp_path,
        runner=runner,
        provider=FakeEvidenceProvider(),
        recorder=recorder,
    )

    outcomes = await executor([BusinessCasePlan(case=case, trial_count=1)])

    assert outcomes[0].task_pass is False
    record = recorder.records[0]
    assert record.task_score == 0
    assert len(record.violations) == 1
    assert record.violations[0].policy_id == "TRADE-SESSION"
    assert record.violations[0].severity == "C0"
    artifact = read_verified_artifact(record.artifact)
    assert artifact["evaluation"]["violations"] == [
        {
            "policy_id": "TRADE-SESSION",
            "severity": "C0",
            "triggered_escalations": ["TRADING-WRONG-EXECUTION"],
        }
    ]


@pytest.mark.asyncio
async def test_plan_order_gives_stable_unique_trial_identities_and_seeds(tmp_path: Path) -> None:
    first = make_case("B1-01")
    second = make_case("B1-02")
    results = {
        ("B1-01", 0): make_runner_result("B1-01", 0),
        ("B1-01", 1): make_runner_result("B1-01", 1),
        ("B1-02", 0): make_runner_result("B1-02", 0),
    }
    runner = FakeRunner(results)
    recorder = FakeRecorder()
    executor = make_executor(
        tmp_path,
        runner=runner,
        provider=FakeEvidenceProvider(),
        recorder=recorder,
        base_random_seed=77,
    )

    await executor(
        [
            BusinessCasePlan(case=first, trial_count=2),
            BusinessCasePlan(case=second, trial_count=1),
        ]
    )

    assert runner.calls == [
        ("B1-01", 0, 77),
        ("B1-01", 1, 78),
        ("B1-02", 0, 79),
    ]
    assert [record.trial_id for record in recorder.records] == [
        "run-pipeline-1.B1-01.0",
        "run-pipeline-1.B1-01.1",
        "run-pipeline-1.B1-02.0",
    ]
    artifacts = [read_verified_artifact(record.artifact) for record in recorder.records]
    assert [artifact["random_seed"] for artifact in artifacts] == [77, 78, 79]


@pytest.mark.asyncio
async def test_duplicate_case_plans_fail_before_runner_or_persistence(tmp_path: Path) -> None:
    case = make_case()
    runner = FakeRunner({(case.case_id, 0): make_runner_result()})
    provider = FakeEvidenceProvider()
    recorder = FakeRecorder()
    root = tmp_path / "artifacts"
    executor = make_executor(
        tmp_path,
        runner=runner,
        provider=provider,
        recorder=recorder,
        artifact_store=ArtifactStore(root),
    )

    with pytest.raises(ValueError, match="duplicate case plan.*B1-01"):
        await executor(
            [
                BusinessCasePlan(case=case, trial_count=1),
                BusinessCasePlan(case=case, trial_count=1),
            ]
        )

    assert runner.calls == []
    assert provider.calls == []
    assert recorder.records == []
    assert list(root.rglob("*.json")) == []


def outcome(
    case_id: str,
    trial_index: int,
    status: str = "valid",
    passed: bool | None = True,
) -> BusinessTrialOutcome:
    return BusinessTrialOutcome(
        case_id=case_id,
        trial_index=trial_index,
        trial_status=status,  # type: ignore[arg-type]
        task_pass=passed,
    )


def test_reliability_summary_all_pass_one_agent_fail_and_invalid() -> None:
    cases = [make_case("B1-01"), make_case("B1-02"), make_case("B1-03")]
    plans = [BusinessCasePlan(case=case, trial_count=3) for case in cases]
    outcomes = [
        outcome("B1-01", 0),
        outcome("B1-01", 1),
        outcome("B1-01", 2),
        outcome("B1-02", 0),
        outcome("B1-02", 1, passed=False),
        outcome("B1-02", 2),
        outcome("B1-03", 0),
        outcome("B1-03", 1),
        outcome("B1-03", 2, "invalid_evidence", None),
    ]

    summaries = summarize_case_reliability(plans, outcomes)

    assert summaries[0].k == 3
    assert summaries[0].valid_trials == 3
    assert summaries[0].pass1 == 1.0
    assert summaries[0].pass_power_k is True
    assert summaries[0].complete is True
    assert summaries[1].valid_trials == 3
    assert summaries[1].pass1 == pytest.approx(2 / 3)
    assert summaries[1].pass_power_k is False
    assert summaries[1].complete is True
    assert summaries[2].valid_trials == 2
    assert summaries[2].pass1 == 1.0
    assert summaries[2].pass_power_k is None
    assert summaries[2].complete is False


def test_reliability_summary_is_incomplete_when_fewer_than_k_trials_arrive() -> None:
    case = make_case()
    summaries = summarize_case_reliability(
        [BusinessCasePlan(case=case, trial_count=3)],
        [outcome(case.case_id, 0), outcome(case.case_id, 1)],
    )

    assert summaries[0].valid_trials == 2
    assert summaries[0].pass1 == 1.0
    assert summaries[0].pass_power_k is None
    assert summaries[0].complete is False
