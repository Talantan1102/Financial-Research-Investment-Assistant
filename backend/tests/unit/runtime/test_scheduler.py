from __future__ import annotations

import asyncio

import pytest
from app.runtime.events import RuntimeEvent, RuntimeEventType
from app.runtime.models import (
    CapabilityDefinition,
    CapabilityType,
    ErrorCategory,
    ExecutionStatus,
    RiskLevel,
    RuntimeErrorInfo,
    RuntimeResult,
)
from app.runtime.scheduler import TaskScheduler
from app.runtime.tasks import Task, TaskGraph


def definition(
    name: str, *, max_attempts: int = 1, concurrency_group: str | None = None
) -> CapabilityDefinition:
    return CapabilityDefinition(
        name=name,
        type=CapabilityType.DATA_TOOL,
        input_schema={},
        output_schema={},
        minimum_risk=RiskLevel.LOW,
        read_only=True,
        idempotent=True,
        default_timeout_s=1,
        max_attempts=max_attempts,
        concurrency_group=concurrency_group,
    )


async def collect(events: list[RuntimeEvent], event: RuntimeEvent) -> None:
    events.append(event)


@pytest.mark.asyncio
async def test_parallel_roots_unlock_dependent_with_resolved_output() -> None:
    graph = TaskGraph(
        tasks=(
            Task(id="a", capability="a", inputs={}),
            Task(id="b", capability="b", inputs={}),
            Task(
                id="c",
                capability="c",
                inputs={"source": "$task.a.output"},
                depends_on=("a", "b"),
            ),
        )
    )
    roots_started = asyncio.Event()
    started: set[str] = set()
    received: dict = {}

    async def execute(task: Task, inputs: dict, _attempt: int) -> RuntimeResult:
        started.add(task.id)
        if task.id in {"a", "b"}:
            if {"a", "b"} <= started:
                roots_started.set()
            await asyncio.wait_for(roots_started.wait(), timeout=0.5)
        else:
            received.update(inputs)
        return RuntimeResult(status=ExecutionStatus.SUCCEEDED, output={"id": task.id})

    results = await TaskScheduler({name: definition(name) for name in ("a", "b", "c")}).run(
        graph, execute, lambda event: collect([], event)
    )

    assert all(result.success for result in results.values())
    assert received == {"source": {"id": "a"}}


@pytest.mark.asyncio
async def test_strong_failure_blocks_dependent_but_not_sibling() -> None:
    graph = TaskGraph(
        tasks=(
            Task(id="a", capability="a", inputs={}),
            Task(id="b", capability="b", inputs={}),
            Task(id="c", capability="c", inputs={}, depends_on=("a",)),
        )
    )
    called: list[str] = []

    async def execute(task: Task, _inputs: dict, _attempt: int) -> RuntimeResult:
        called.append(task.id)
        if task.id == "a":
            return RuntimeResult(
                status=ExecutionStatus.FAILED,
                error=RuntimeErrorInfo(
                    code="boom",
                    category=ErrorCategory.EXECUTION_ERROR,
                    message="boom",
                    retryable=False,
                ),
            )
        return RuntimeResult(status=ExecutionStatus.SUCCEEDED, output={})

    results = await TaskScheduler({name: definition(name) for name in ("a", "b", "c")}).run(
        graph, execute, lambda event: collect([], event)
    )

    assert set(called) == {"a", "b"}
    assert results["c"].error is not None
    assert results["c"].error.category is ErrorCategory.DEPENDENCY_FAILED


@pytest.mark.asyncio
async def test_concurrency_group_serializes_without_failure_dependency() -> None:
    called: list[str] = []

    async def execute(task: Task, _inputs: dict, _attempt: int) -> RuntimeResult:
        called.append(task.id)
        if task.id == "a":
            return RuntimeResult(
                status=ExecutionStatus.FAILED,
                error=RuntimeErrorInfo(
                    code="boom",
                    category=ErrorCategory.EXECUTION_ERROR,
                    message="boom",
                    retryable=False,
                ),
            )
        return RuntimeResult(status=ExecutionStatus.SUCCEEDED, output={})

    group = {name: definition(name, concurrency_group="state") for name in ("a", "b")}
    results = await TaskScheduler(group).run(
        TaskGraph(
            tasks=(
                Task(id="a", capability="a", inputs={}, concurrency_group="state"),
                Task(id="b", capability="b", inputs={}, concurrency_group="state"),
            )
        ),
        execute,
        lambda event: collect([], event),
    )

    assert called == ["a", "b"]
    assert results["a"].success is False
    assert results["b"].success is True


@pytest.mark.asyncio
async def test_retries_safe_transient_failure_and_records_effective_input() -> None:
    attempts = 0

    async def execute(_task: Task, _inputs: dict, attempt: int) -> RuntimeResult:
        nonlocal attempts
        attempts += 1
        if attempt == 1:
            return RuntimeResult(
                status=ExecutionStatus.FAILED,
                error=RuntimeErrorInfo(
                    code="temporary",
                    category=ErrorCategory.TRANSIENT,
                    message="temporary",
                    retryable=True,
                ),
            )
        return RuntimeResult(status=ExecutionStatus.SUCCEEDED, output={"ok": True})

    results = await TaskScheduler({"read": definition("read", max_attempts=2)}).run(
        TaskGraph(tasks=(Task(id="read", capability="read", inputs={"x": 1}),)),
        execute,
        lambda event: collect([], event),
    )

    assert attempts == 2
    assert results["read"].attempt == 2
    assert results["read"].effective_input == {"x": 1}


@pytest.mark.asyncio
async def test_cancellation_emits_each_terminal_and_graph_completed_once() -> None:
    events: list[RuntimeEvent] = []
    entered = asyncio.Event()

    async def execute(_task: Task, _inputs: dict, _attempt: int) -> RuntimeResult:
        entered.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    running = asyncio.create_task(
        TaskScheduler({"a": definition("a"), "b": definition("b")}).run(
            TaskGraph(
                tasks=(
                    Task(id="a", capability="a", inputs={}),
                    Task(id="b", capability="b", inputs={}, depends_on=("a",)),
                )
            ),
            execute,
            lambda event: collect(events, event),
        )
    )
    await entered.wait()
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running

    assert sum(event.type is RuntimeEventType.GRAPH_COMPLETED for event in events) == 1
    assert {event.task_id for event in events if event.type is RuntimeEventType.TASK_CANCELLED} == {
        "a",
        "b",
    }
