from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest
from eval.chatloop.business_cli import BusinessCasePlan, BusinessTrialOutcome
from eval.chatloop.business_runtime import ProductionBusinessExecutor
from eval.chatloop.case_loader import load_catalog


class FakeRuntime:
    def __init__(self, *, cleanup_error: Exception | None = None) -> None:
        self.cleanup_error = cleanup_error
        self.database_name = "fria_eval_fake"
        self.closed = False

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
