"""Production composition and lifecycle for the business conversation evaluator."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from hashlib import sha256
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.engine import URL

from eval.chatloop.artifact_store import ArtifactStore
from eval.chatloop.business_cli import (
    BusinessCasePlan,
    BusinessExecutor,
    BusinessTrialOutcome,
)
from eval.chatloop.business_pipeline import BusinessPlanExecutor
from eval.chatloop.business_runner import (
    BusinessRunner,
    DirectToolLoopBusinessExecutor,
    DurableHttpBusinessExecutor,
    current_durable_tool_fault_plans,
)
from eval.chatloop.disposable_runtime import DisposableEvalRuntime, RuntimeCleanupError
from eval.chatloop.durable_runtime import (
    AsyncCleanup,
    DurableResourceFactory,
    InProcessDurableDriver,
)
from eval.chatloop.environment import CaseEnvironmentManager
from eval.chatloop.faults import FaultInjectingHub
from eval.chatloop.judge_calibration import JudgeCalibrationGate
from eval.chatloop.policy_registry import PolicyRegistry
from eval.chatloop.recorder import ChatloopEvalRecorder, new_run_id, now_iso
from eval.chatloop.structured_evidence import (
    SEMANTIC_JUDGE_PROMPT_SHA256,
    SEMANTIC_JUDGE_RUBRIC_VERSION,
    BusinessStructuredEvidenceProvider,
    LLMSemanticEvidenceJudge,
)

RuntimeFactory = Callable[..., Any]
RecorderFactory = Callable[[], Any]
ComponentBuilder = Callable[..., BusinessExecutor]
HistoryExporter = Callable[[], Any]


class ProductionBusinessExecutor:
    """Provision, execute, persist, and prove cleanup for one CLI invocation."""

    def __init__(
        self,
        *,
        admin_dsn_factory: Callable[[], str] | None = None,
        runtime_factory: RuntimeFactory | None = None,
        recorder_factory: RecorderFactory | None = None,
        component_builder: ComponentBuilder | None = None,
        run_id_factory: Callable[[], str] = new_run_id,
        history_exporter: HistoryExporter | None = None,
    ) -> None:
        self._admin_dsn_factory = admin_dsn_factory or _admin_dsn_from_env
        self._runtime_factory = runtime_factory or DisposableEvalRuntime.provision
        self._recorder_factory = recorder_factory or ChatloopEvalRecorder
        self._component_builder = component_builder or _build_components
        self._run_id_factory = run_id_factory
        self._history_exporter = history_exporter or _export_history

    async def __call__(
        self,
        plans: Sequence[BusinessCasePlan],
    ) -> Sequence[BusinessTrialOutcome]:
        frozen_plans = tuple(plans)
        if not frozen_plans:
            raise ValueError("business execution requires at least one plan")
        run_id = self._run_id_factory()
        started = time.perf_counter()
        recorder = self._recorder_factory()
        versions = _versions()
        recorder.record(_run_start(run_id, frozen_plans, versions), [])
        runtime: Any | None = None

        try:
            runtime = self._runtime_factory(
                admin_dsn=self._admin_dsn_factory(),
                run_id=run_id,
            )
            executor = self._component_builder(
                runtime=runtime,
                run_id=run_id,
                plans=frozen_plans,
                recorder=recorder,
                versions=versions,
            )
            outcomes = tuple(await executor(frozen_plans))
        except BaseException as execution_error:
            if runtime is not None:
                try:
                    await runtime.aclose()
                except BaseException as cleanup_error:
                    _finish(
                        recorder,
                        run_id,
                        started,
                        status=_cleanup_failure_status(
                            cleanup_error,
                            execution_failed=True,
                        ),
                        config_patch={
                            "failure": _error_text(execution_error),
                            "cleanup_failure": _error_text(cleanup_error),
                        },
                    )
                    raise cleanup_error from execution_error
            _finish(
                recorder,
                run_id,
                started,
                status=(
                    _cleanup_failure_status(execution_error, execution_failed=True)
                    if isinstance(execution_error, RuntimeCleanupError)
                    else "harness_failed"
                ),
                config_patch={"failure": _error_text(execution_error)},
            )
            raise

        try:
            await runtime.aclose()
        except BaseException as cleanup_error:
            _finish(
                recorder,
                run_id,
                started,
                status=_cleanup_failure_status(cleanup_error),
                config_patch={"cleanup_failure": _error_text(cleanup_error)},
            )
            raise

        invalid = sum(item.trial_status != "valid" for item in outcomes)
        task_failures = sum(
            item.trial_status == "valid" and item.task_pass is False for item in outcomes
        )
        if invalid:
            status = "completed_with_invalid_trials"
        elif task_failures:
            status = "completed_with_agent_failures"
        else:
            status = "completed"
        _finish(
            recorder,
            run_id,
            started,
            status=status,
            config_patch={
                "runtime_database": runtime.database_name,
                "total_trials": len(outcomes),
                "valid_trials": len(outcomes) - invalid,
                "invalid_trials": invalid,
                "task_failures": task_failures,
            },
        )
        try:
            self._history_exporter()
        except Exception as export_error:
            _finish(
                recorder,
                run_id,
                started,
                status="report_failed",
                config_patch={"report_failure": _error_text(export_error)},
            )
            raise
        return outcomes


def _cleanup_failure_status(
    error: BaseException,
    *,
    execution_failed: bool = False,
) -> str:
    if (
        isinstance(error, RuntimeCleanupError)
        and not error.database_leaked
        and not error.memory_leaked
    ):
        return "harness_failed" if execution_failed else "cleanup_failed"
    return "runtime_leaked"


def _build_components(
    *,
    runtime: DisposableEvalRuntime,
    run_id: str,
    plans: Sequence[BusinessCasePlan],
    recorder: ChatloopEvalRecorder,
    versions: dict[str, str],
) -> BusinessExecutor:
    from app.services.openai_client import build_llm_service_from_env

    effective_versions = dict(versions)
    gate: JudgeCalibrationGate | None = None
    if _plans_require_semantic_judge(plans):
        calibration_path = os.getenv("CHATLOOP_JUDGE_CALIBRATION_PATH")
        if not calibration_path:
            raise RuntimeError(
                "CHATLOOP_JUDGE_CALIBRATION_PATH is required before the business semantic judge can run"
            )
        gate = JudgeCalibrationGate.from_jsonl(
            calibration_path,
            expected_identity={
                "judge_model": versions["model"],
                "judge_prompt_sha256": SEMANTIC_JUDGE_PROMPT_SHA256,
                "rubric_version": SEMANTIC_JUDGE_RUBRIC_VERSION,
            },
        )
        gate.require_calibrated()
        calibration_kappa = gate.result.cohen_kappa
        if calibration_kappa is None:  # defensive: calibrated gates require a defined kappa
            raise RuntimeError("business semantic judge calibration kappa is undefined")
        effective_versions.update(
            {
                "judge_calibration_sha256": sha256(Path(calibration_path).read_bytes()).hexdigest(),
                "judge_calibration_samples": str(gate.result.sample_count),
                "judge_calibration_kappa": f"{calibration_kappa:.6f}",
                "judge_calibration_agreement": f"{gate.result.agreement:.6f}",
                "judge_prompt_sha256": SEMANTIC_JUDGE_PROMPT_SHA256,
                "judge_rubric_version": SEMANTIC_JUDGE_RUBRIC_VERSION,
            }
        )
    llm = build_llm_service_from_env()
    eval_memory: Any = object()
    if _plans_require_memory(plans):
        runtime.provision_memory_isolation()
        eval_memory = _build_eval_memory(runtime)
    semantic_judge: LLMSemanticEvidenceJudge | None = None
    if gate is not None:
        semantic_judge = LLMSemanticEvidenceJudge(
            llm=llm,
            judge_model=versions["model"],
            calibration_gate=gate,
        )
    durable_driver = InProcessDurableDriver.lazy(
        runtime.async_session_factory,
        resource_factory=_durable_resource_factory(
            runtime=runtime,
            llm=llm,
            memory=eval_memory,
        ),
    )
    runtime.bind_durable_driver(durable_driver)
    from app.processes.run_api import create_run_api_app

    run_api = create_run_api_app(session_factory=runtime.async_session_factory)
    manager = CaseEnvironmentManager(
        runtime,
        external_memory_cleanup=(
            runtime.cleanup_memory_mirrors if _plans_require_memory(plans) else None
        ),
    )
    runner = BusinessRunner(
        manager,
        direct_executor=DirectToolLoopBusinessExecutor(
            runtime.async_session_factory,
            sync_session_factory=runtime.sync_session_factory,
            subprocess_env=runtime.subprocess_env,
            memory=eval_memory,
        ),
        durable_executor=DurableHttpBusinessExecutor(
            runtime.async_session_factory,
            base_url="http://run-api",
            timeout_s=float(os.getenv("CHATLOOP_EVAL_RUN_TIMEOUT_S", "60")),
            client_transport=httpx.ASGITransport(app=run_api),
            progress_callback=durable_driver.advance,
        ),
    )
    provider = BusinessStructuredEvidenceProvider(
        versions=effective_versions,
        semantic_judge=semantic_judge,
    )
    artifact_root = Path(
        os.getenv(
            "CHATLOOP_EVAL_ARTIFACT_ROOT",
            str(Path(__file__).resolve().parent / "results" / "business"),
        )
    )
    catalog = _catalog_for_plans()
    return BusinessPlanExecutor(
        runner=runner,
        evidence_provider=provider,
        policy_registry=PolicyRegistry.default(),
        artifact_store=ArtifactStore(artifact_root),
        trial_recorder=recorder,
        versions=effective_versions,
        policy_as_of=catalog.policy_as_of,
        run_id=run_id,
        base_random_seed=int(os.getenv("CHATLOOP_EVAL_BASE_SEED", "20260728")),
    )


def _durable_resource_factory(
    *,
    runtime: DisposableEvalRuntime,
    llm: Any,
    memory: Any = None,
) -> DurableResourceFactory:
    async def build() -> tuple[Any, AsyncCleanup]:
        return await _build_durable_worker_resources(
            runtime=runtime,
            llm=llm,
            memory=memory,
        )

    return build


async def _build_durable_worker_resources(
    *,
    runtime: DisposableEvalRuntime,
    llm: Any,
    memory: Any = None,
) -> tuple[Any, AsyncCleanup]:
    """Open the real MCP/ChatLoop worker stack with all-or-nothing cleanup."""
    from app.chatloop.worker_wiring import build_heavy_singletons
    from app.services.mcp_client import MCPClient
    from app.services.run_chat_worker import (
        build_chat_executor_builder,
        load_tool_risk_policy,
        resolve_llm_identity,
    )

    mcp_context = MCPClient.from_subprocess(
        profile="chat_tools",
        env_overrides=runtime.subprocess_env,
    )
    mcp_client = await mcp_context.__aenter__()
    try:
        singletons = await build_heavy_singletons(
            session_factory=runtime.async_session_factory,
            sync_session_factory=runtime.sync_session_factory,
            mcp_client=mcp_client,
            llm=llm,
            memory=memory if memory is not None else object(),
        )
        provider, model = resolve_llm_identity(llm)
        executor_builder = build_chat_executor_builder(
            singletons,
            provider=provider,
            model=model,
            risk_policy=load_tool_risk_policy(os.environ),
            tool_hub_decorator=lambda hub: FaultInjectingHub(
                hub,
                list(current_durable_tool_fault_plans()),
            ),
        )
    except BaseException:
        await mcp_context.__aexit__(*sys.exc_info())
        raise

    async def cleanup() -> None:
        await mcp_context.__aexit__(None, None, None)

    return executor_builder, cleanup


def _plans_require_semantic_judge(plans: Sequence[BusinessCasePlan]) -> bool:
    for plan in plans:
        case = plan.case
        assertions = (
            *case.required_assertions,
            *case.forbidden_outcomes,
            *case.expected_state_changes,
            *(
                assertion
                for outcome in case.acceptable_outcomes
                for assertion in outcome.assertions
            ),
        )
        if any(
            assertion.source == "judge" and assertion.operator != "absent"
            for assertion in assertions
        ):
            return True
    return False


def _plans_require_memory(plans: Sequence[BusinessCasePlan]) -> bool:
    return any(
        "memory" in plan.case.initial_state.business_state
        or any("memory" in tool.lower() for tool in plan.case.available_tools)
        for plan in plans
    )


def _build_eval_memory(runtime: DisposableEvalRuntime) -> Any:
    from app.mcp_server.tools.memory._common import build_memory_from_env

    return build_memory_from_env(
        pg_session_factory=runtime.sync_session_factory,
        milvus_client=runtime.memory_client,
        collection_name=runtime.memory_collection_name,
    )


def _catalog_for_plans():
    from eval.chatloop.case_loader import load_catalog

    return load_catalog()


def _versions() -> dict[str, str]:
    from app.chatloop.system_prompt import CHAT_SYSTEM_PROMPT
    from app.services.llm_identity import resolve_llm_identity_from_env

    from eval.chatloop.case_loader import load_catalog

    catalog = load_catalog()
    _provider, model = resolve_llm_identity_from_env()
    return {
        "case": catalog.manifest.catalog_version,
        "policy": catalog.policy_version,
        "evaluator": "business-eval-v1",
        "model": model,
        "prompt_sha256": sha256(CHAT_SYSTEM_PROMPT.encode("utf-8")).hexdigest(),
        "git_sha": _full_git_sha(),
    }


def _run_start(
    run_id: str,
    plans: Sequence[BusinessCasePlan],
    versions: dict[str, str],
) -> dict[str, Any]:
    counts = {plan.trial_count for plan in plans}
    return {
        "run_id": run_id,
        "created_at": now_iso(),
        "git_sha": versions["git_sha"],
        "mode": "business",
        "dispatch": "real",
        "sut_model": versions["model"],
        "judge_model": versions["model"],
        "simulator_model": None,
        "k": next(iter(counts)) if len(counts) == 1 else None,
        "max_steps": 6,
        "max_turns": None,
        "golden_file": str(_catalog_for_plans().root / "catalog.json"),
        "case_count": len(plans),
        "system_prompt_sha": versions["prompt_sha256"],
        "thresholds_json": None,
        "sampling_json": {
            "sut": {"temperature": "provider-default", "seed_applied": False},
            "judge": {"temperature": "provider-default", "seed_applied": False},
        },
        "duration_ms": None,
        "cost_cny": None,
        "total_tokens": None,
        "status": "running",
        "config_json": {
            "case_ids": [plan.case.case_id for plan in plans],
            "trial_counts": {plan.case.case_id: plan.trial_count for plan in plans},
            "suite_types": {plan.case.case_id: plan.case.suite_type.value for plan in plans},
            "case_version": versions["case"],
            "policy_version": versions["policy"],
            "evaluator_version": versions["evaluator"],
        },
    }


def _finish(
    recorder: Any,
    run_id: str,
    started: float,
    *,
    status: str,
    config_patch: dict[str, Any],
) -> None:
    recorder.finish_run(
        run_id,
        status=status,
        duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
        cost_cny=None,
        total_tokens=None,
        config_patch=config_patch,
    )


def _admin_dsn_from_env() -> str:
    password = os.getenv("POSTGRES_PASSWORD")
    if not password:
        raise RuntimeError("POSTGRES_PASSWORD is required for disposable eval runtime")
    return URL.create(
        "postgresql",
        username=os.getenv("POSTGRES_USER", "postgres"),
        password=password,
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        database=os.getenv("CHATLOOP_EVAL_ADMIN_DB", "postgres"),
    ).render_as_string(hide_password=False)


def _full_git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _error_text(error: BaseException) -> str:
    return f"{type(error).__name__}: {error}"


def _export_history() -> None:
    from eval.chatloop.export_dashboard import export_history

    export_history()


__all__ = ["ProductionBusinessExecutor"]
