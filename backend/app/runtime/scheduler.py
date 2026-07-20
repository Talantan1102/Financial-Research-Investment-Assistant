"""Bounded dependency-aware scheduler for one planner turn."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, TypeAlias

from app.runtime.dependencies import DependencyResolver
from app.runtime.events import RuntimeEvent, RuntimeEventType
from app.runtime.models import (
    CapabilityDefinition,
    ErrorCategory,
    ExecutionStatus,
    RuntimeErrorInfo,
    RuntimeResult,
)
from app.runtime.tasks import Task, TaskGraph

ExecuteTask: TypeAlias = Callable[[Task, dict[str, Any], int], Awaitable[RuntimeResult]]
EmitEvent: TypeAlias = Callable[[RuntimeEvent], Awaitable[None]]
logger = logging.getLogger(__name__)


class TaskScheduler:
    def __init__(
        self,
        definitions: Mapping[str, CapabilityDefinition],
        *,
        max_concurrency: int = 8,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least one")
        self._definitions = definitions
        self._max_concurrency = max_concurrency
        self._resolver = DependencyResolver()

    async def run(
        self, graph: TaskGraph, execute: ExecuteTask, emit: EmitEvent
    ) -> dict[str, RuntimeResult]:
        self._resolver.validate(graph)
        results: dict[str, RuntimeResult] = {}
        emitted_terminal: set[str] = set()
        current_attempt = {task.id: 0 for task in graph.tasks}
        semaphore = asyncio.Semaphore(self._max_concurrency)
        running: dict[asyncio.Task[RuntimeResult], Task] = {}

        async def emit_terminal(task_id: str, result: RuntimeResult) -> None:
            if task_id in emitted_terminal:
                return
            emitted_terminal.add(task_id)
            event_type = (
                RuntimeEventType.TASK_COMPLETED
                if result.status is ExecutionStatus.SUCCEEDED
                else RuntimeEventType.TASK_CANCELLED
                if result.status is ExecutionStatus.CANCELLED
                else RuntimeEventType.TASK_FAILED
            )
            await self._safe_emit(
                emit,
                RuntimeEvent(
                    type=event_type,
                    task_id=task_id,
                    attempt=result.attempt,
                    data={"result": result.model_dump(mode="json")},
                ),
            )

        try:
            while len(results) < len(graph.tasks):
                progressed = False
                running_ids = {task.id for task in running.values()}
                for task in graph.tasks:
                    if task.id in results or task.id in running_ids:
                        continue
                    failed = [
                        dependency
                        for dependency in task.depends_on
                        if dependency in results and not results[dependency].success
                    ]
                    if failed:
                        result = self._failure(
                            "dependency_failed",
                            ErrorCategory.DEPENDENCY_FAILED,
                            f"dependencies failed: {', '.join(failed)}",
                        )
                        results[task.id] = result
                        await emit_terminal(task.id, result)
                        progressed = True

                running_ids = {task.id for task in running.values()}
                ready = [
                    task
                    for task in graph.tasks
                    if task.id not in results
                    and task.id not in running_ids
                    and all(
                        dependency in results and results[dependency].success
                        for dependency in task.depends_on
                    )
                    and all(dependency in results for dependency in task.optional_depends_on)
                ]
                for task in ready:
                    running[
                        asyncio.create_task(
                            self._run_one(
                                task,
                                dict(results),
                                execute,
                                emit,
                                semaphore,
                                current_attempt,
                            )
                        )
                    ] = task
                    progressed = True

                if running:
                    completed, _ = await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)
                    for future in completed:
                        task = running.pop(future)
                        result = future.result()
                        results[task.id] = result
                        await emit_terminal(task.id, result)
                    progressed = True
                if not progressed:
                    raise RuntimeError("validated task graph made no scheduling progress")
        except asyncio.CancelledError:
            for future in running:
                future.cancel()
            if running:
                await asyncio.gather(*running, return_exceptions=True)
            for task in graph.tasks:
                if task.id not in results:
                    result = self._failure(
                        "cancelled",
                        ErrorCategory.CANCELLED,
                        "task graph was cancelled",
                        status=ExecutionStatus.CANCELLED,
                        attempt=current_attempt[task.id],
                    )
                    results[task.id] = result
                    await emit_terminal(task.id, result)
            raise
        finally:
            completion = asyncio.create_task(
                self._safe_emit(
                    emit,
                    RuntimeEvent(
                        type=RuntimeEventType.GRAPH_COMPLETED,
                        data={
                            "results": {
                                task_id: result.model_dump(mode="json")
                                for task_id, result in results.items()
                            }
                        },
                    ),
                )
            )
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.shield(completion)
        return results

    async def _run_one(
        self,
        task: Task,
        completed: Mapping[str, RuntimeResult],
        execute: ExecuteTask,
        emit: EmitEvent,
        semaphore: asyncio.Semaphore,
        current_attempt: dict[str, int],
    ) -> RuntimeResult:
        outputs = {
            task_id: result.output for task_id, result in completed.items() if result.success
        }
        inputs = self._resolver.resolve_inputs(task, outputs)
        if task.optional_depends_on:

            def error_payload(dependency: str) -> dict[str, Any] | None:
                error = completed[dependency].error
                return error.model_dump(mode="json") if error is not None else None

            inputs["_optional_dependencies"] = {
                dependency: {
                    "status": completed[dependency].status.value,
                    "output": completed[dependency].output,
                    "error": error_payload(dependency),
                }
                for dependency in task.optional_depends_on
            }
        definition = self._definitions.get(task.capability)
        if definition is None:
            return self._failure(
                "capability_definition_missing",
                ErrorCategory.SYSTEM_ERROR,
                f"no definition for capability {task.capability!r}",
            )

        async with semaphore:
            for attempt in range(1, definition.max_attempts + 1):
                current_attempt[task.id] = attempt
                await self._safe_emit(
                    emit,
                    RuntimeEvent(
                        type=RuntimeEventType.TASK_STARTED,
                        task_id=task.id,
                        attempt=attempt,
                    ),
                )
                try:
                    result = await execute(task, inputs, attempt)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    result = self._failure(
                        "execute_boundary_error", ErrorCategory.SYSTEM_ERROR, str(exc)
                    )
                result = result.model_copy(
                    update={
                        "attempt": attempt,
                        "effective_input": (
                            result.effective_input if result.effective_input is not None else inputs
                        ),
                    }
                )
                if not self._should_retry(result, definition, attempt):
                    return result
        raise AssertionError("attempt loop always returns")

    @staticmethod
    def _should_retry(
        result: RuntimeResult, definition: CapabilityDefinition, attempt: int
    ) -> bool:
        return bool(
            result.error is not None
            and result.error.retryable
            and result.error.category in {ErrorCategory.TRANSIENT, ErrorCategory.TIMEOUT}
            and (definition.read_only or definition.idempotent)
            and attempt < definition.max_attempts
        )

    @staticmethod
    def _failure(
        code: str,
        category: ErrorCategory,
        message: str,
        *,
        status: ExecutionStatus = ExecutionStatus.FAILED,
        attempt: int = 0,
    ) -> RuntimeResult:
        return RuntimeResult(
            status=status,
            attempt=attempt,
            error=RuntimeErrorInfo(
                code=code,
                category=category,
                message=message or code,
                retryable=False,
            ),
        )

    @staticmethod
    async def _safe_emit(emit: EmitEvent, event: RuntimeEvent) -> None:
        try:
            await emit(event)
        except asyncio.CancelledError:
            task = asyncio.current_task()
            if task is not None and task.cancelling():
                raise
            logger.warning("runtime event sink raised CancelledError", exc_info=True)
        except Exception:
            logger.warning("runtime event sink failed", exc_info=True)
