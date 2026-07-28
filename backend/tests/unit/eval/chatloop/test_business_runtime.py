from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from app.services import openai_client
from eval.chatloop import business_runtime
from eval.chatloop.business_cli import BusinessCasePlan, BusinessTrialOutcome
from eval.chatloop.business_runtime import ProductionBusinessExecutor
from eval.chatloop.case_loader import load_catalog
from eval.chatloop.case_schema import AcceptableOutcome, AssertionSpec
from eval.chatloop.disposable_runtime import RuntimeCleanupError


class FakeRuntime:
    def __init__(self, *, cleanup_error: Exception | None = None) -> None:
        self.cleanup_error = cleanup_error
        self.database_name = "fria_eval_fake"
        self.closed = False
        self.async_session_factory = object()
        self.sync_session_factory = object()
        self.subprocess_env: dict[str, str] = {}
        self.durable_driver: object | None = None
        self.memory_client = object()
        self.memory_collection_name = "chat_memory_eval_fake"
        self.memory_provisioned = False

    def bind_durable_driver(self, driver: object) -> None:
        self.durable_driver = driver

    def provision_memory_isolation(self) -> None:
        self.memory_provisioned = True

    async def cleanup_memory_mirrors(
        self,
        _edge_ids: list[str],
        _node_ids: list[str],
    ) -> None:
        return None

    async def aclose(self) -> None:
        if self.cleanup_error is not None:
            raise self.cleanup_error
        self.closed = True


class FakeRecorder:
    def __init__(self) -> None:
        self.starts: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
        self.finishes: list[dict[str, Any]] = []

    def record(self, run: dict[str, Any], metrics: list[dict[str, Any]]) -> str:
        self.starts.append((run, metrics))
        return str(run["run_id"])

    def finish_run(self, run_id: str, **values: Any) -> None:
        self.finishes.append({"run_id": run_id, **values})


class FakePlanExecutor:
    def __init__(
        self,
        outcomes: Sequence[BusinessTrialOutcome] = (),
        *,
        error: Exception | None = None,
    ) -> None:
        self.outcomes = tuple(outcomes)
        self.error = error

    async def __call__(self, plans: Sequence[BusinessCasePlan]):
        del plans
        if self.error is not None:
            raise self.error
        return self.outcomes


def _plan() -> BusinessCasePlan:
    return BusinessCasePlan(case=load_catalog().by_id("B1-01"), trial_count=1)


def test_versions_record_the_effective_environment_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MOCK_TUSHARE_MODEL", "qwen-plus")
    monkeypatch.setattr(business_runtime, "_full_git_sha", lambda: "test-git")

    versions = business_runtime._versions()

    assert versions["model"] == "qwen-plus"
    assert versions["git_sha"] == "test-git"


def _assertion(*, source: str, operator: str = "equals") -> AssertionSpec:
    return AssertionSpec.model_validate(
        {
            "assertion_id": f"test-{source}-{operator}",
            "source": source,
            "operator": operator,
            "path": "quality.result",
            "expected": "pass",
        }
    )


def _plan_with_assertions(
    *required: AssertionSpec,
    acceptable: tuple[AssertionSpec, ...] = (),
) -> BusinessCasePlan:
    case = (
        load_catalog()
        .by_id("B1-01")
        .model_copy(
            update={
                "required_assertions": list(required),
                "forbidden_outcomes": [],
                "expected_state_changes": [],
                "acceptable_outcomes": (
                    [AcceptableOutcome(name_zh="测试允许结果", assertions=list(acceptable))]
                    if acceptable
                    else []
                ),
            }
        )
    )
    return BusinessCasePlan(case=case, trial_count=1)


def _build_test_components(
    monkeypatch: pytest.MonkeyPatch,
    plans: Sequence[BusinessCasePlan],
) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def capture_provider(*, versions: dict[str, str], semantic_judge: object | None) -> object:
        captured["provider_versions"] = dict(versions)
        captured["semantic_judge"] = semantic_judge
        return object()

    def capture_plan_executor(**kwargs: Any) -> object:
        captured["executor_versions"] = dict(kwargs["versions"])
        captured["evidence_provider"] = kwargs["evidence_provider"]
        captured["runner"] = kwargs["runner"]
        return object()

    monkeypatch.setattr(
        business_runtime,
        "CaseEnvironmentManager",
        lambda _runtime, **_kwargs: object(),
    )
    monkeypatch.setattr(business_runtime, "BusinessStructuredEvidenceProvider", capture_provider)
    monkeypatch.setattr(business_runtime, "BusinessPlanExecutor", capture_plan_executor)
    captured["executor"] = business_runtime._build_components(
        runtime=FakeRuntime(),
        run_id="run-components-test",
        plans=plans,
        recorder=FakeRecorder(),
        versions={
            "case": "test-cases",
            "policy": "test-policy",
            "evaluator": "test-evaluator",
            "model": "test-model",
            "prompt_sha256": "test-prompt",
            "git_sha": "test-git",
        },
    )
    return captured


def test_deterministic_only_components_do_not_require_judge_calibration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CHATLOOP_JUDGE_CALIBRATION_PATH", raising=False)
    built_llms: list[object] = []
    monkeypatch.setattr(
        openai_client,
        "build_llm_service_from_env",
        lambda: built_llms.append(object()) or built_llms[-1],
    )

    captured = _build_test_components(
        monkeypatch,
        [_plan_with_assertions(_assertion(source="answer", operator="exists"))],
    )

    assert captured["semantic_judge"] is None
    assert built_llms, "the Agent still requires its production LLM service"
    assert not any(key.startswith("judge_") for key in captured["provider_versions"])


def test_components_bind_lazy_real_durable_executor_without_starting_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CHATLOOP_JUDGE_CALIBRATION_PATH", raising=False)

    class FakeLLM:
        provider = "scripted"
        default_model = "scripted-v1"

    monkeypatch.setattr(openai_client, "build_llm_service_from_env", FakeLLM)
    runtime = FakeRuntime()
    mcp_starts: list[str] = []
    monkeypatch.setattr(
        business_runtime,
        "_build_durable_worker_resources",
        lambda **_kwargs: mcp_starts.append("started"),
    )
    captured: dict[str, Any] = {}

    monkeypatch.setattr(
        business_runtime,
        "CaseEnvironmentManager",
        lambda _runtime, **_kwargs: object(),
    )
    monkeypatch.setattr(
        business_runtime,
        "BusinessStructuredEvidenceProvider",
        lambda **_kwargs: object(),
    )

    def capture_plan_executor(**kwargs: Any) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(business_runtime, "BusinessPlanExecutor", capture_plan_executor)
    business_runtime._build_components(
        runtime=runtime,
        run_id="run-lazy-durable",
        plans=[_plan_with_assertions(_assertion(source="answer", operator="exists"))],
        recorder=FakeRecorder(),
        versions={
            "case": "test-cases",
            "policy": "test-policy",
            "evaluator": "test-evaluator",
            "model": "test-model",
            "prompt_sha256": "test-prompt",
            "git_sha": "test-git",
        },
    )

    assert runtime.durable_driver is not None
    assert runtime.durable_driver.is_open
    assert runtime.durable_driver.is_started is False
    assert mcp_starts == []
    assert isinstance(
        captured["runner"]._executors["durable"],
        business_runtime.DurableHttpBusinessExecutor,
    )


def test_memory_case_provisions_and_injects_run_scoped_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CHATLOOP_JUDGE_CALIBRATION_PATH", raising=False)
    monkeypatch.setattr(openai_client, "build_llm_service_from_env", object)
    runtime = FakeRuntime()
    eval_memory = object()
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        business_runtime,
        "_build_eval_memory",
        lambda selected_runtime: eval_memory if selected_runtime is runtime else None,
    )
    monkeypatch.setattr(
        business_runtime,
        "CaseEnvironmentManager",
        lambda _runtime, **_kwargs: object(),
    )
    monkeypatch.setattr(
        business_runtime,
        "BusinessStructuredEvidenceProvider",
        lambda **_kwargs: object(),
    )

    def capture_plan_executor(**kwargs: Any) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(business_runtime, "BusinessPlanExecutor", capture_plan_executor)
    memory_case = (
        load_catalog()
        .by_id("B4-06")
        .model_copy(
            update={
                "required_assertions": [],
                "forbidden_outcomes": [],
                "expected_state_changes": [],
                "acceptable_outcomes": [],
            }
        )
    )
    plan = BusinessCasePlan(case=memory_case, trial_count=1)

    business_runtime._build_components(
        runtime=runtime,
        run_id="run-memory",
        plans=[plan],
        recorder=FakeRecorder(),
        versions={
            "case": "test-cases",
            "policy": "test-policy",
            "evaluator": "test-evaluator",
            "model": "test-model",
            "prompt_sha256": "test-prompt",
            "git_sha": "test-git",
        },
    )

    assert runtime.memory_provisioned is True
    assert captured["runner"]._executors["direct"]._memory is eval_memory


@pytest.mark.asyncio
async def test_durable_resource_build_failure_exits_mcp_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.chatloop import worker_wiring
    from app.services.mcp_client import MCPClient

    events: list[str] = []

    class FailingMCPContext:
        async def __aenter__(self) -> object:
            events.append("enter")
            return object()

        async def __aexit__(self, *_args: object) -> None:
            events.append("exit")

    monkeypatch.setattr(
        MCPClient,
        "from_subprocess",
        lambda **_kwargs: FailingMCPContext(),
    )

    async def fail_singletons(**_kwargs: object) -> object:
        raise RuntimeError("singleton build failed")

    monkeypatch.setattr(worker_wiring, "build_heavy_singletons", fail_singletons)
    runtime = FakeRuntime()

    class FakeLLM:
        provider = "scripted"
        default_model = "scripted-v1"

    driver = business_runtime.InProcessDurableDriver.lazy(
        runtime.async_session_factory,
        resource_factory=business_runtime._durable_resource_factory(
            runtime=runtime,
            llm=FakeLLM(),
        ),
    )
    runtime.bind_durable_driver(driver)

    with pytest.raises(RuntimeError, match="singleton build failed"):
        await driver.start()

    assert events == ["enter", "exit"]
    assert driver.is_open is False
    assert driver.is_started is False
    await driver.aclose()


@pytest.mark.asyncio
async def test_durable_resource_cleanup_exits_successfully_started_mcp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.chatloop import worker_wiring
    from app.services.mcp_client import MCPClient

    events: list[str] = []

    class MCPContext:
        async def __aenter__(self) -> object:
            events.append("enter")
            return object()

        async def __aexit__(self, *_args: object) -> None:
            events.append("exit")

    monkeypatch.setattr(MCPClient, "from_subprocess", lambda **_kwargs: MCPContext())

    async def build_singletons(**_kwargs: object) -> object:
        return object()

    monkeypatch.setattr(worker_wiring, "build_heavy_singletons", build_singletons)

    class FakeLLM:
        provider = "scripted"
        default_model = "scripted-v1"

    _builder, cleanup = await business_runtime._build_durable_worker_resources(
        runtime=FakeRuntime(),
        llm=FakeLLM(),
    )
    assert events == ["enter"]

    await cleanup()

    assert events == ["enter", "exit"]


def test_absent_judge_assertion_does_not_require_judge_calibration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CHATLOOP_JUDGE_CALIBRATION_PATH", raising=False)
    monkeypatch.setattr(openai_client, "build_llm_service_from_env", object)

    captured = _build_test_components(
        monkeypatch,
        [_plan_with_assertions(_assertion(source="judge", operator="absent"))],
    )

    assert captured["semantic_judge"] is None


def test_judge_assertion_requires_calibration_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CHATLOOP_JUDGE_CALIBRATION_PATH", raising=False)
    llm_builds: list[object] = []
    monkeypatch.setattr(
        openai_client,
        "build_llm_service_from_env",
        lambda: llm_builds.append(object()),
    )

    with pytest.raises(RuntimeError, match="CHATLOOP_JUDGE_CALIBRATION_PATH is required"):
        _build_test_components(
            monkeypatch,
            [_plan_with_assertions(_assertion(source="judge"))],
        )
    assert llm_builds == []


def test_mixed_plans_require_calibration_when_acceptable_outcome_uses_judge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CHATLOOP_JUDGE_CALIBRATION_PATH", raising=False)
    monkeypatch.setattr(openai_client, "build_llm_service_from_env", object)
    deterministic = _plan_with_assertions(_assertion(source="tools", operator="exists"))
    semantic = _plan_with_assertions(acceptable=(_assertion(source="judge"),))

    with pytest.raises(RuntimeError, match="CHATLOOP_JUDGE_CALIBRATION_PATH is required"):
        _build_test_components(monkeypatch, [deterministic, semantic])


@pytest.mark.parametrize(
    "assertion_field",
    ["required_assertions", "forbidden_outcomes", "expected_state_changes"],
)
def test_each_top_level_assertion_group_can_require_semantic_judge(
    assertion_field: str,
) -> None:
    case = (
        load_catalog()
        .by_id("B1-01")
        .model_copy(
            update={
                "required_assertions": [],
                "forbidden_outcomes": [],
                "expected_state_changes": [],
                "acceptable_outcomes": [],
                assertion_field: [_assertion(source="judge")],
            }
        )
    )

    assert business_runtime._plans_require_semantic_judge(
        [BusinessCasePlan(case=case, trial_count=1)]
    )


def test_calibrated_judge_keeps_identity_checks_and_provenance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calibration_path = tmp_path / "judge-calibration.jsonl"
    calibration_path.write_text("calibrated\n", encoding="utf-8")
    monkeypatch.setenv("CHATLOOP_JUDGE_CALIBRATION_PATH", str(calibration_path))
    monkeypatch.setattr(openai_client, "build_llm_service_from_env", object)
    calibration_events: dict[str, Any] = {}

    class FakeGate:
        result = SimpleNamespace(cohen_kappa=0.8, sample_count=30, agreement=0.9)

        def require_calibrated(self) -> None:
            calibration_events["required"] = True

    class FakeGateFactory:
        @staticmethod
        def from_jsonl(path: str, *, expected_identity: dict[str, str]) -> FakeGate:
            calibration_events["path"] = path
            calibration_events["identity"] = expected_identity
            return FakeGate()

    monkeypatch.setattr(business_runtime, "JudgeCalibrationGate", FakeGateFactory)

    captured = _build_test_components(
        monkeypatch,
        [_plan_with_assertions(_assertion(source="judge"))],
    )

    versions = captured["provider_versions"]
    assert captured["semantic_judge"] is not None
    assert calibration_events == {
        "path": str(calibration_path),
        "identity": {
            "judge_model": "test-model",
            "judge_prompt_sha256": business_runtime.SEMANTIC_JUDGE_PROMPT_SHA256,
            "rubric_version": business_runtime.SEMANTIC_JUDGE_RUBRIC_VERSION,
        },
        "required": True,
    }
    assert versions["judge_calibration_samples"] == "30"
    assert versions["judge_calibration_kappa"] == "0.800000"
    assert versions["judge_calibration_agreement"] == "0.900000"


@pytest.mark.asyncio
async def test_runtime_records_start_closes_database_and_finishes_agent_failure() -> None:
    runtime = FakeRuntime()
    recorder = FakeRecorder()
    exports: list[str] = []
    outcome = BusinessTrialOutcome("B1-01", 0, "valid", False)
    executor = ProductionBusinessExecutor(
        admin_dsn_factory=lambda: "postgresql://admin/postgres",
        runtime_factory=lambda **_kwargs: runtime,
        recorder_factory=lambda: recorder,
        component_builder=lambda **_kwargs: FakePlanExecutor([outcome]),
        run_id_factory=lambda: "run-business-1",
        history_exporter=lambda: exports.append("exported"),
    )

    returned = await executor([_plan()])

    assert returned == (outcome,)
    assert runtime.closed is True
    assert recorder.starts[0][0]["status"] == "running"
    assert recorder.starts[0][0]["mode"] == "business"
    assert recorder.finishes[0]["status"] == "completed_with_agent_failures"
    assert recorder.finishes[0]["config_patch"]["task_failures"] == 1
    assert exports == ["exported"]


@pytest.mark.asyncio
async def test_component_failure_is_recorded_and_runtime_is_still_closed() -> None:
    runtime = FakeRuntime()
    recorder = FakeRecorder()
    executor = ProductionBusinessExecutor(
        admin_dsn_factory=lambda: "postgresql://admin/postgres",
        runtime_factory=lambda **_kwargs: runtime,
        recorder_factory=lambda: recorder,
        component_builder=lambda **_kwargs: FakePlanExecutor(error=RuntimeError("boom")),
        run_id_factory=lambda: "run-business-2",
    )

    with pytest.raises(RuntimeError, match="boom"):
        await executor([_plan()])

    assert runtime.closed is True
    assert recorder.finishes[0]["status"] == "harness_failed"
    assert recorder.finishes[0]["config_patch"]["failure"] == "RuntimeError: boom"


@pytest.mark.asyncio
async def test_cleanup_failure_is_loud_and_run_is_marked_runtime_leaked() -> None:
    runtime = FakeRuntime(cleanup_error=OSError("drop failed"))
    recorder = FakeRecorder()
    outcome = BusinessTrialOutcome("B1-01", 0, "valid", True)
    executor = ProductionBusinessExecutor(
        admin_dsn_factory=lambda: "postgresql://admin/postgres",
        runtime_factory=lambda **_kwargs: runtime,
        recorder_factory=lambda: recorder,
        component_builder=lambda **_kwargs: FakePlanExecutor([outcome]),
        run_id_factory=lambda: "run-business-3",
    )

    with pytest.raises(OSError, match="drop failed"):
        await executor([_plan()])

    assert recorder.finishes[0]["status"] == "runtime_leaked"


@pytest.mark.asyncio
async def test_cleanup_failure_after_confirmed_drop_is_not_marked_runtime_leaked() -> None:
    cleanup_error = RuntimeCleanupError(
        database_name="fria_eval_fake",
        database_leaked=False,
        failures=(("durable_driver", OSError("worker offline failed")),),
    )
    runtime = FakeRuntime(cleanup_error=cleanup_error)
    recorder = FakeRecorder()
    outcome = BusinessTrialOutcome("B1-01", 0, "valid", True)
    executor = ProductionBusinessExecutor(
        admin_dsn_factory=lambda: "postgresql://admin/postgres",
        runtime_factory=lambda **_kwargs: runtime,
        recorder_factory=lambda: recorder,
        component_builder=lambda **_kwargs: FakePlanExecutor([outcome]),
        run_id_factory=lambda: "run-business-cleanup-removed",
    )

    with pytest.raises(RuntimeCleanupError, match="worker offline failed"):
        await executor([_plan()])

    assert recorder.finishes[0]["status"] == "cleanup_failed"


@pytest.mark.asyncio
async def test_memory_collection_leak_is_marked_runtime_leaked() -> None:
    cleanup_error = RuntimeCleanupError(
        database_name="fria_eval_fake",
        database_leaked=False,
        memory_collection_name="chat_memory_eval_leaked",
        memory_leaked=True,
        failures=(("memory_collection", OSError("drop failed")),),
    )
    runtime = FakeRuntime(cleanup_error=cleanup_error)
    recorder = FakeRecorder()
    outcome = BusinessTrialOutcome("B1-01", 0, "valid", True)
    executor = ProductionBusinessExecutor(
        admin_dsn_factory=lambda: "postgresql://admin/postgres",
        runtime_factory=lambda **_kwargs: runtime,
        recorder_factory=lambda: recorder,
        component_builder=lambda **_kwargs: FakePlanExecutor([outcome]),
        run_id_factory=lambda: "run-business-memory-leaked",
    )

    with pytest.raises(RuntimeCleanupError, match="drop failed"):
        await executor([_plan()])

    assert recorder.finishes[0]["status"] == "runtime_leaked"


@pytest.mark.asyncio
async def test_execution_failure_with_confirmed_drop_stays_harness_failed() -> None:
    cleanup_error = RuntimeCleanupError(
        database_name="fria_eval_fake",
        database_leaked=False,
        failures=(("async_engine", OSError("dispose failed")),),
    )
    runtime = FakeRuntime(cleanup_error=cleanup_error)
    recorder = FakeRecorder()
    executor = ProductionBusinessExecutor(
        admin_dsn_factory=lambda: "postgresql://admin/postgres",
        runtime_factory=lambda **_kwargs: runtime,
        recorder_factory=lambda: recorder,
        component_builder=lambda **_kwargs: FakePlanExecutor(error=RuntimeError("boom")),
        run_id_factory=lambda: "run-business-failed-cleanup-removed",
    )

    with pytest.raises(RuntimeCleanupError, match="dispose failed"):
        await executor([_plan()])

    assert recorder.finishes[0]["status"] == "harness_failed"
    assert recorder.finishes[0]["config_patch"]["failure"] == "RuntimeError: boom"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("database_leaked", "expected_status"),
    [(True, "runtime_leaked"), (False, "harness_failed")],
)
async def test_runtime_factory_cleanup_error_uses_proven_leak_state(
    database_leaked: bool,
    expected_status: str,
) -> None:
    recorder = FakeRecorder()
    factory_error = RuntimeCleanupError(
        database_name="fria_eval_factory",
        database_leaked=database_leaked,
        failures=(("drop_database", OSError("factory cleanup failed")),),
    )

    def fail_runtime_factory(**_kwargs: Any) -> Any:
        raise factory_error

    executor = ProductionBusinessExecutor(
        admin_dsn_factory=lambda: "postgresql://admin/postgres",
        runtime_factory=fail_runtime_factory,
        recorder_factory=lambda: recorder,
        component_builder=lambda **_kwargs: FakePlanExecutor(),
        run_id_factory=lambda: f"run-factory-cleanup-{database_leaked}",
    )

    with pytest.raises(RuntimeCleanupError, match="factory cleanup failed"):
        await executor([_plan()])

    assert recorder.finishes[0]["status"] == expected_status


@pytest.mark.asyncio
async def test_report_export_failure_is_loud_and_marks_run() -> None:
    runtime = FakeRuntime()
    recorder = FakeRecorder()
    outcome = BusinessTrialOutcome("B1-01", 0, "valid", True)

    def fail_export() -> None:
        raise OSError("dashboard unavailable")

    executor = ProductionBusinessExecutor(
        admin_dsn_factory=lambda: "postgresql://admin/postgres",
        runtime_factory=lambda **_kwargs: runtime,
        recorder_factory=lambda: recorder,
        component_builder=lambda **_kwargs: FakePlanExecutor([outcome]),
        run_id_factory=lambda: "run-business-4",
        history_exporter=fail_export,
    )

    with pytest.raises(OSError, match="dashboard unavailable"):
        await executor([_plan()])

    assert runtime.closed is True
    assert recorder.finishes[-1]["status"] == "report_failed"
