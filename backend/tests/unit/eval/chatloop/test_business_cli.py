"""Unit tests for the business-evaluation CLI selection and exit contract."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import pytest
from eval.chatloop import run_eval
from eval.chatloop.business_cli import (
    BusinessCasePlan,
    BusinessCliDependencies,
    BusinessCliSummary,
    BusinessTrialOutcome,
    run_business_cli,
)
from eval.chatloop.case_loader import CaseCatalog, load_catalog
from eval.chatloop.case_schema import SuiteType


class RecordingExecutor:
    def __init__(
        self,
        *,
        status: str = "valid",
        task_pass: bool | None = True,
    ) -> None:
        self.status = status
        self.task_pass = task_pass
        self.calls: list[tuple[BusinessCasePlan, ...]] = []

    async def __call__(
        self,
        plans: Sequence[BusinessCasePlan],
    ) -> Sequence[BusinessTrialOutcome]:
        frozen = tuple(plans)
        self.calls.append(frozen)
        return tuple(
            BusinessTrialOutcome(
                case_id=plan.case.case_id,
                trial_index=trial_index,
                trial_status=self.status,
                task_pass=self.task_pass,
            )
            for plan in frozen
            for trial_index in range(plan.trial_count)
        )


class RecordingResumer:
    def __init__(self, summary: BusinessCliSummary) -> None:
        self.summary = summary
        self.run_ids: list[str] = []

    async def __call__(self, eval_run_id: str) -> BusinessCliSummary:
        self.run_ids.append(eval_run_id)
        return self.summary


@pytest.fixture(scope="module")
def real_catalog() -> CaseCatalog:
    return load_catalog()


@pytest.fixture
def mixed_catalog(real_catalog: CaseCatalog) -> CaseCatalog:
    capability_b1 = real_catalog.by_id("B1-01").model_copy(update={"trial_count": 2})
    capability_b2 = real_catalog.by_id("B2-01")
    regression_b3 = real_catalog.by_id("B3-01").model_copy(
        update={"suite_type": SuiteType.REGRESSION}
    )
    return replace(real_catalog, cases=(capability_b1, capability_b2, regression_b3))


def _deps(
    catalog: CaseCatalog,
    executor: RecordingExecutor | None,
    *,
    resumer: RecordingResumer | None = None,
) -> BusinessCliDependencies:
    if resumer is not None:
        return BusinessCliDependencies(
            catalog_loader=lambda: catalog,
            executor=executor,
            resumer=resumer,
            output=lambda _message: None,
        )
    return BusinessCliDependencies(
        catalog_loader=lambda: catalog,
        executor=executor,
        output=lambda _message: None,
    )


def test_validate_catalog_loads_the_real_120_cases(real_catalog: CaseCatalog) -> None:
    result = run_business_cli(
        ["--business", "--validate-catalog"],
        dependencies=_deps(real_catalog, None),
    )

    assert result.exit_code == 0
    assert result.summary.selected_cases == 120
    assert result.summary.total_trials == 0


def test_run_eval_business_branch_precedes_legacy_scenario_loading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def legacy_loader_must_not_run(_path: object) -> object:
        raise AssertionError("legacy scenario loader ran for --business")

    monkeypatch.setattr(run_eval, "load_scenarios", legacy_loader_must_not_run)

    assert run_eval.main(["--business", "--validate-catalog"]) == 0


def test_validate_catalog_process_does_not_require_runtime_database_env() -> None:
    repo_root = Path(__file__).resolve().parents[5]
    env = os.environ.copy()
    env.pop("POSTGRES_PASSWORD", None)
    env["PYTHONPATH"] = str(repo_root / "backend")

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "eval.chatloop.run_eval",
            "--business",
            "--validate-catalog",
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=repo_root,
        env=env,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Catalog valid: 120 cases" in completed.stdout


def test_capability_suite_requires_batch_or_all(mixed_catalog: CaseCatalog) -> None:
    executor = RecordingExecutor()

    result = run_business_cli(
        ["--business", "--suite", "Capability"],
        dependencies=_deps(mixed_catalog, executor),
    )

    assert result.exit_code == 2
    assert executor.calls == []


def test_regression_suite_rejects_redundant_all(mixed_catalog: CaseCatalog) -> None:
    executor = RecordingExecutor()

    result = run_business_cli(
        ["--business", "--suite", "Regression", "--all"],
        dependencies=_deps(mixed_catalog, executor),
    )

    assert result.exit_code == 2
    assert executor.calls == []


@pytest.mark.parametrize(
    ("argv", "expected_case_ids"),
    [
        (["--business", "--suite", "Capability", "--batch", "1"], ("B1-01",)),
        (
            ["--business", "--suite", "Capability", "--all"],
            ("B1-01", "B2-01"),
        ),
        (["--business", "--case", "B3-01"], ("B3-01",)),
        (["--business", "--cases", "B3-01,B1-01"], ("B3-01", "B1-01")),
    ],
)
def test_business_selectors_choose_only_requested_cases(
    mixed_catalog: CaseCatalog,
    argv: list[str],
    expected_case_ids: tuple[str, ...],
) -> None:
    executor = RecordingExecutor()

    result = run_business_cli(argv, dependencies=_deps(mixed_catalog, executor))

    assert result.exit_code == 0
    assert tuple(plan.case.case_id for plan in executor.calls[0]) == expected_case_ids


def test_k_overrides_catalog_trial_count(mixed_catalog: CaseCatalog) -> None:
    executor = RecordingExecutor()

    result = run_business_cli(
        ["--business", "--case", "B1-01", "--k", "3"],
        dependencies=_deps(mixed_catalog, executor),
    )

    assert result.exit_code == 0
    assert executor.calls[0][0].trial_count == 3
    assert result.summary.total_trials == 3


def test_cases_selector_keeps_k_override(mixed_catalog: CaseCatalog) -> None:
    executor = RecordingExecutor()

    result = run_business_cli(
        ["--business", "--cases", "B1-01,B2-01", "--k", "3"],
        dependencies=_deps(mixed_catalog, executor),
    )

    assert result.exit_code == 0
    assert [plan.trial_count for plan in executor.calls[0]] == [3, 3]


def test_catalog_trial_count_is_used_without_k(mixed_catalog: CaseCatalog) -> None:
    executor = RecordingExecutor()

    result = run_business_cli(
        ["--business", "--case", "B1-01"],
        dependencies=_deps(mixed_catalog, executor),
    )

    assert result.exit_code == 0
    assert executor.calls[0][0].trial_count == 2
    assert result.summary.total_trials == 2


def test_capability_agent_failures_do_not_create_a_fake_release_gate(
    mixed_catalog: CaseCatalog,
) -> None:
    executor = RecordingExecutor(task_pass=False)

    result = run_business_cli(
        ["--business", "--suite", "Capability", "--batch", "1"],
        dependencies=_deps(mixed_catalog, executor),
    )

    assert result.exit_code == 0
    assert result.summary.task_failures == 2


def test_regression_mandatory_failure_returns_one(mixed_catalog: CaseCatalog) -> None:
    executor = RecordingExecutor(task_pass=False)

    result = run_business_cli(
        ["--business", "--suite", "Regression", "--k", "3"],
        dependencies=_deps(mixed_catalog, executor),
    )

    assert result.exit_code == 1
    assert result.summary.regression_failures == 3


@pytest.mark.parametrize("status", ["harness_failed", "invalid_evidence"])
def test_invalid_trial_status_returns_two(
    mixed_catalog: CaseCatalog,
    status: str,
) -> None:
    executor = RecordingExecutor(status=status, task_pass=None)

    result = run_business_cli(
        ["--business", "--case", "B1-01"],
        dependencies=_deps(mixed_catalog, executor),
    )

    assert result.exit_code == 2
    assert result.summary.invalid_trials == 2


def test_execution_without_disposable_runtime_fails_closed(mixed_catalog: CaseCatalog) -> None:
    result = run_business_cli(
        ["--business", "--case", "B1-01"],
        dependencies=_deps(mixed_catalog, None),
    )

    assert result.exit_code == 2
    assert "disposable runtime" in (result.error or "")


def test_unknown_case_returns_two_without_running(mixed_catalog: CaseCatalog) -> None:
    executor = RecordingExecutor()

    result = run_business_cli(
        ["--business", "--case", "B9-99"],
        dependencies=_deps(mixed_catalog, executor),
    )

    assert result.exit_code == 2
    assert executor.calls == []


def test_missing_trial_result_is_a_harness_failure(mixed_catalog: CaseCatalog) -> None:
    async def incomplete_executor(
        _plans: Sequence[BusinessCasePlan],
    ) -> Sequence[BusinessTrialOutcome]:
        return ()

    result = run_business_cli(
        ["--business", "--case", "B1-01"],
        dependencies=BusinessCliDependencies(
            catalog_loader=lambda: mixed_catalog,
            executor=incomplete_executor,
            output=lambda _message: None,
        ),
    )

    assert result.exit_code == 2
    assert "trial identities" in (result.error or "")


def test_resume_run_calls_injected_resumer_with_run_id(mixed_catalog: CaseCatalog) -> None:
    resumer = RecordingResumer(BusinessCliSummary(selected_cases=2, total_trials=2, valid_trials=2))

    result = run_business_cli(
        ["--business", "--resume-run", "eval-run-123"],
        dependencies=_deps(mixed_catalog, None, resumer=resumer),
    )

    assert result.exit_code == 0
    assert result.summary.total_trials == 2
    assert resumer.run_ids == ["eval-run-123"]


def test_resume_run_invalid_summary_returns_two(mixed_catalog: CaseCatalog) -> None:
    resumer = RecordingResumer(
        BusinessCliSummary(selected_cases=1, total_trials=1, invalid_trials=1)
    )

    result = run_business_cli(
        ["--business", "--resume-run", "eval-invalid"],
        dependencies=_deps(mixed_catalog, None, resumer=resumer),
    )

    assert result.exit_code == 2


def test_resume_run_regression_failure_returns_one(mixed_catalog: CaseCatalog) -> None:
    resumer = RecordingResumer(
        BusinessCliSummary(
            selected_cases=1,
            total_trials=1,
            valid_trials=1,
            task_failures=1,
            regression_failures=1,
        )
    )

    result = run_business_cli(
        ["--business", "--resume-run", "eval-regression"],
        dependencies=_deps(mixed_catalog, None, resumer=resumer),
    )

    assert result.exit_code == 1


def test_resume_run_without_safe_runtime_fails_closed(mixed_catalog: CaseCatalog) -> None:
    result = run_business_cli(
        ["--business", "--resume-run", "eval-run-123"],
        dependencies=_deps(mixed_catalog, None),
    )

    assert result.exit_code == 2
    assert "resume runtime" in (result.error or "")


@pytest.mark.parametrize(
    "conflict",
    [
        ["--validate-catalog"],
        ["--suite", "Regression"],
        ["--case", "B1-01"],
        ["--cases", "B1-01,B2-01"],
        ["--batch", "1"],
        ["--all"],
        ["--k", "3"],
    ],
)
def test_resume_run_rejects_catalog_selection_and_k(
    mixed_catalog: CaseCatalog,
    conflict: list[str],
) -> None:
    resumer = RecordingResumer(BusinessCliSummary())

    result = run_business_cli(
        ["--business", "--resume-run", "eval-run-123", *conflict],
        dependencies=_deps(mixed_catalog, None, resumer=resumer),
    )

    assert result.exit_code == 2
    assert resumer.run_ids == []
