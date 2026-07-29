"""Pure selection, injectable execution, and exit semantics for business evals."""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal, NoReturn, Protocol

from eval.chatloop.case_loader import CaseCatalog, load_catalog
from eval.chatloop.case_schema import ConversationCase, SuiteType

BusinessTrialStatus = Literal["valid", "harness_failed", "invalid_evidence"]


class BusinessCliUsageError(ValueError):
    """The requested business-evaluation selection is invalid or ambiguous."""


@dataclass(frozen=True, slots=True)
class BusinessCasePlan:
    """One selected catalog case and the number of trials to execute."""

    case: ConversationCase
    trial_count: int


@dataclass(frozen=True, slots=True)
class BusinessTrialOutcome:
    """The minimal trial facts needed to apply CLI exit semantics."""

    case_id: str
    trial_index: int
    trial_status: BusinessTrialStatus
    task_pass: bool | None


class BusinessExecutor(Protocol):
    async def __call__(
        self,
        plans: Sequence[BusinessCasePlan],
    ) -> Sequence[BusinessTrialOutcome]: ...


class BusinessResumer(Protocol):
    async def __call__(self, eval_run_id: str) -> BusinessCliSummary: ...


@dataclass(frozen=True, slots=True)
class BusinessCliDependencies:
    """Runtime seams; execution is deliberately absent from production defaults."""

    catalog_loader: Callable[[], CaseCatalog] = load_catalog
    executor: BusinessExecutor | None = None
    resumer: BusinessResumer | None = None
    output: Callable[[str], None] = print


@dataclass(frozen=True, slots=True)
class BusinessCliSummary:
    selected_cases: int = 0
    total_trials: int = 0
    valid_trials: int = 0
    task_failures: int = 0
    regression_failures: int = 0
    invalid_trials: int = 0


@dataclass(frozen=True, slots=True)
class BusinessCliResult:
    exit_code: int
    summary: BusinessCliSummary
    error: str | None = None


@dataclass(frozen=True, slots=True)
class BusinessCliOptions:
    validate_catalog: bool
    suite: SuiteType | None
    batch: int | None
    case_id: str | None
    case_ids: tuple[str, ...]
    all_cases: bool
    k: int | None
    resume_run_id: str | None


class _BusinessArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise BusinessCliUsageError(message)


def parse_business_args(argv: Sequence[str]) -> BusinessCliOptions:
    """Parse and validate only the new business CLI, without loading any data."""
    parser = _BusinessArgumentParser(description="conversational business evaluation")
    parser.add_argument("--business", action="store_true")
    parser.add_argument("--validate-catalog", action="store_true")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--suite", choices=[item.value for item in SuiteType])
    selection.add_argument("--case", dest="case_id")
    selection.add_argument("--cases")
    selection.add_argument("--resume-run", dest="resume_run_id")
    parser.add_argument("--batch", type=int)
    parser.add_argument("--all", dest="all_cases", action="store_true")
    parser.add_argument("--k", type=int)
    parsed = parser.parse_args(list(argv))

    if not parsed.business:
        raise BusinessCliUsageError("business CLI requires --business")
    if parsed.k is not None and parsed.k < 1:
        raise BusinessCliUsageError("--k must be a positive integer")
    if parsed.batch is not None and parsed.batch not in range(1, 9):
        raise BusinessCliUsageError("--batch must be between 1 and 8")

    has_execution_option = any(
        (
            parsed.suite is not None,
            parsed.case_id is not None,
            parsed.cases is not None,
            parsed.resume_run_id is not None,
            parsed.batch is not None,
            parsed.all_cases,
            parsed.k is not None,
        )
    )
    if parsed.validate_catalog:
        if has_execution_option:
            raise BusinessCliUsageError(
                "--validate-catalog cannot be combined with execution options"
            )
        return BusinessCliOptions(True, None, None, None, (), False, None, None)

    if parsed.resume_run_id is not None:
        if not parsed.resume_run_id.strip():
            raise BusinessCliUsageError("--resume-run requires a non-empty eval run ID")
        if parsed.batch is not None or parsed.all_cases or parsed.k is not None:
            raise BusinessCliUsageError(
                "--resume-run cannot be combined with catalog selectors or --k"
            )
        return BusinessCliOptions(
            validate_catalog=False,
            suite=None,
            batch=None,
            case_id=None,
            case_ids=(),
            all_cases=False,
            k=None,
            resume_run_id=parsed.resume_run_id,
        )

    suite = SuiteType(parsed.suite) if parsed.suite is not None else None
    case_ids = _parse_case_ids(parsed.cases)
    if suite is SuiteType.CAPABILITY:
        if (parsed.batch is None) == (not parsed.all_cases):
            raise BusinessCliUsageError("Capability requires exactly one of --batch or --all")
    elif suite is SuiteType.REGRESSION:
        if parsed.batch is not None:
            raise BusinessCliUsageError(
                "Regression selects the full suite; --batch is not supported"
            )
        if parsed.all_cases:
            raise BusinessCliUsageError("Regression already selects the full suite; omit --all")
    elif parsed.batch is not None or parsed.all_cases:
        raise BusinessCliUsageError("--batch and --all require --suite")

    if parsed.case_id is not None or case_ids:
        if parsed.batch is not None or parsed.all_cases:
            raise BusinessCliUsageError("case selectors cannot be combined with --batch or --all")
    elif suite is None:
        raise BusinessCliUsageError("select --suite, --case, or --cases")

    return BusinessCliOptions(
        validate_catalog=False,
        suite=suite,
        batch=parsed.batch,
        case_id=parsed.case_id,
        case_ids=case_ids,
        all_cases=parsed.all_cases,
        k=parsed.k,
        resume_run_id=None,
    )


def select_business_cases(
    catalog: CaseCatalog,
    options: BusinessCliOptions,
) -> tuple[ConversationCase, ...]:
    """Apply suite and explicit-ID filters in deterministic order."""
    if options.case_id is not None:
        return (catalog.by_id(options.case_id),)
    if options.case_ids:
        return tuple(catalog.by_id(case_id) for case_id in options.case_ids)
    if options.suite is None:
        return ()

    selected = tuple(case for case in catalog.cases if case.suite_type is options.suite)
    if options.batch is not None:
        prefix = f"B{options.batch}-"
        selected = tuple(case for case in selected if case.case_id.startswith(prefix))
    return selected


def summarize_business_run(
    plans: Sequence[BusinessCasePlan],
    outcomes: Sequence[BusinessTrialOutcome],
) -> BusinessCliSummary:
    """Validate result completeness before counting Agent and harness failures."""
    expected_identities = Counter(
        (plan.case.case_id, trial_index)
        for plan in plans
        for trial_index in range(plan.trial_count)
    )
    actual_identities = Counter((outcome.case_id, outcome.trial_index) for outcome in outcomes)
    if actual_identities != expected_identities:
        raise BusinessCliUsageError("executor returned incomplete or duplicate trial identities")

    suites = {plan.case.case_id: plan.case.suite_type for plan in plans}
    for outcome in outcomes:
        if outcome.trial_status not in {"valid", "harness_failed", "invalid_evidence"}:
            raise BusinessCliUsageError(f"unknown trial_status: {outcome.trial_status}")
        if outcome.trial_status == "valid" and not isinstance(outcome.task_pass, bool):
            raise BusinessCliUsageError("valid trial requires boolean task_pass")
        if outcome.trial_status != "valid" and outcome.task_pass is not None:
            raise BusinessCliUsageError("invalid trial requires task_pass=null")

    valid = tuple(outcome for outcome in outcomes if outcome.trial_status == "valid")
    task_failures = tuple(outcome for outcome in valid if outcome.task_pass is False)
    regression_failures = tuple(
        outcome for outcome in task_failures if suites[outcome.case_id] is SuiteType.REGRESSION
    )
    return BusinessCliSummary(
        selected_cases=len(plans),
        total_trials=len(outcomes),
        valid_trials=len(valid),
        task_failures=len(task_failures),
        regression_failures=len(regression_failures),
        invalid_trials=len(outcomes) - len(valid),
    )


def business_exit_code(summary: BusinessCliSummary) -> int:
    """Apply harness-invalid precedence, then Regression release semantics."""
    if summary.invalid_trials:
        return 2
    if summary.regression_failures:
        return 1
    return 0


def run_business_cli(
    argv: Sequence[str],
    *,
    dependencies: BusinessCliDependencies | None = None,
) -> BusinessCliResult:
    """Load, select, optionally execute, and return a testable CLI result."""
    deps = dependencies or BusinessCliDependencies()
    try:
        options = parse_business_args(argv)
        if options.resume_run_id is not None:
            if deps.resumer is None:
                raise BusinessCliUsageError(
                    "business resume requires an injected safe resume runtime"
                )
            summary = asyncio.run(deps.resumer(options.resume_run_id))
            deps.output(_format_run_summary(summary))
            return BusinessCliResult(exit_code=business_exit_code(summary), summary=summary)

        catalog = deps.catalog_loader()
        if options.validate_catalog:
            summary = BusinessCliSummary(selected_cases=len(catalog.cases))
            deps.output(_format_catalog_validation(catalog))
            return BusinessCliResult(exit_code=0, summary=summary)

        selected = select_business_cases(catalog, options)
        if not selected:
            raise BusinessCliUsageError("selection matched no catalog cases")
        plans = tuple(
            BusinessCasePlan(case=case, trial_count=options.k or case.trial_count)
            for case in selected
        )
        executor = deps.executor
        if executor is None:
            if dependencies is not None:
                raise BusinessCliUsageError(
                    "business execution requires an injected safe disposable runtime"
                )
            executor = _default_business_executor()
        outcomes: tuple[BusinessTrialOutcome, ...] = tuple(asyncio.run(executor(plans)))
        summary = summarize_business_run(plans, outcomes)
        deps.output(_format_run_summary(summary))
        return BusinessCliResult(exit_code=business_exit_code(summary), summary=summary)
    except Exception as exc:  # noqa: BLE001 - CLI must fail closed on harness/config errors
        summary = BusinessCliSummary()
        error = f"{type(exc).__name__}: {exc}"
        deps.output(error)
        return BusinessCliResult(exit_code=2, summary=summary, error=error)


def _parse_case_ids(raw: str | None) -> tuple[str, ...]:
    if raw is None:
        return ()
    case_ids = tuple(part.strip() for part in raw.split(","))
    if not case_ids or any(not case_id for case_id in case_ids):
        raise BusinessCliUsageError("--cases requires comma-separated non-empty case IDs")
    if len(set(case_ids)) != len(case_ids):
        raise BusinessCliUsageError("--cases cannot contain duplicate case IDs")
    return case_ids


def _format_catalog_validation(catalog: CaseCatalog) -> str:
    counts = ", ".join(f"B{batch}={count}" for batch, count in catalog.batch_counts.items())
    return f"Catalog valid: {len(catalog.cases)} cases ({counts})"


def _format_run_summary(summary: BusinessCliSummary) -> str:
    return (
        f"Business eval: cases={summary.selected_cases}, trials={summary.total_trials}, "
        f"valid={summary.valid_trials}, task_failures={summary.task_failures}, "
        f"regression_failures={summary.regression_failures}, "
        f"invalid={summary.invalid_trials}"
    )


def _default_business_executor() -> BusinessExecutor:
    """Import the stateful runtime only after a validated execution selection."""
    from eval.chatloop.business_runtime import ProductionBusinessExecutor

    return ProductionBusinessExecutor()


__all__ = [
    "BusinessCasePlan",
    "BusinessCliDependencies",
    "BusinessCliOptions",
    "BusinessCliResult",
    "BusinessCliSummary",
    "BusinessCliUsageError",
    "BusinessExecutor",
    "BusinessResumer",
    "BusinessTrialOutcome",
    "business_exit_code",
    "parse_business_args",
    "run_business_cli",
    "select_business_cases",
    "summarize_business_run",
]
