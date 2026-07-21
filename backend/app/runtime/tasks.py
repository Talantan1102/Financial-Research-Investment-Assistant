"""Request-local task graph contracts and ``StepToolCall`` builder."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.runtime.models import CapabilityDefinition, ExecutionStatus
from app.services.llm_step import StepToolCall

_TASK_ID = "__task_id"
_DEPENDS_ON = "__depends_on"
_OPTIONAL_DEPENDS_ON = "__optional_depends_on"
_RESERVED = frozenset({_TASK_ID, _DEPENDS_ON, _OPTIONAL_DEPENDS_ON})


class Task(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    capability: str = Field(min_length=1)
    inputs: dict[str, Any]
    depends_on: tuple[str, ...] = ()
    optional_depends_on: tuple[str, ...] = ()
    status: ExecutionStatus = ExecutionStatus.PENDING
    concurrency_group: str | None = None


class TaskGraph(BaseModel):
    model_config = ConfigDict(frozen=True)

    tasks: tuple[Task, ...]

    @property
    def task_ids(self) -> tuple[str, ...]:
        return tuple(task.id for task in self.tasks)

    def get(self, task_id: str) -> Task:
        for task in self.tasks:
            if task.id == task_id:
                return task
        raise KeyError(task_id)


class TaskBuilder:
    """Build a bounded DAG without changing the mainline planner protocol."""

    def __init__(self, definitions: Mapping[str, CapabilityDefinition] | None = None) -> None:
        self._definitions = definitions or {}

    def build(self, calls: Sequence[StepToolCall], *, parallelizable: bool = True) -> TaskGraph:
        tasks: list[Task] = []
        for call in calls:
            raw = call.parsed_args
            task_id = _metadata_task_id(raw, call.id)
            explicit = _metadata_ids(raw, _DEPENDS_ON)
            references = _referenced_task_ids(
                {key: value for key, value in raw.items() if key not in _RESERVED}
            )
            definition = self._definitions.get(call.name)
            tasks.append(
                Task(
                    id=task_id,
                    capability=call.name,
                    inputs={key: value for key, value in raw.items() if key not in _RESERVED},
                    depends_on=tuple(dict.fromkeys((*explicit, *references))),
                    optional_depends_on=_metadata_ids(raw, _OPTIONAL_DEPENDS_ON),
                    concurrency_group=(
                        definition.concurrency_group if definition is not None else None
                    ),
                )
            )

        order = _stable_topological_order(tasks)
        if order is None:
            return TaskGraph(tasks=tuple(tasks))
        dependencies = {task.id: list(task.depends_on) for task in tasks}
        if not parallelizable:
            for predecessor, current in zip(order, order[1:]):
                dependencies[current].append(predecessor)
        return TaskGraph(
            tasks=tuple(
                task.model_copy(update={"depends_on": tuple(dict.fromkeys(dependencies[task.id]))})
                for task in tasks
            )
        )


def _metadata_task_id(args: Mapping[str, Any], fallback: str) -> str:
    value = args.get(_TASK_ID, fallback)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{_TASK_ID} must be a non-empty string")
    return value


def _metadata_ids(args: Mapping[str, Any], name: str) -> tuple[str, ...]:
    value = args.get(name, ())
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise ValueError(f"{name} must be a list of non-empty task ids")
    return tuple(dict.fromkeys(value))


def _referenced_task_ids(value: Any) -> tuple[str, ...]:
    from app.runtime.dependencies import task_reference_id

    found: list[str] = []
    if isinstance(value, str):
        reference = task_reference_id(value)
        if reference is not None:
            found.append(reference)
    elif isinstance(value, Mapping):
        for nested in value.values():
            found.extend(_referenced_task_ids(nested))
    elif isinstance(value, (list, tuple)):
        for nested in value:
            found.extend(_referenced_task_ids(nested))
    return tuple(dict.fromkeys(found))


def _stable_topological_order(tasks: Sequence[Task]) -> tuple[str, ...] | None:
    ids = tuple(task.id for task in tasks)
    known = set(ids)
    if len(known) != len(ids):
        return None
    indegree = dict.fromkeys(ids, 0)
    dependents: dict[str, list[str]] = {task_id: [] for task_id in ids}
    for task in tasks:
        for dependency in (*task.depends_on, *task.optional_depends_on):
            if dependency not in known or dependency == task.id:
                return None
            indegree[task.id] += 1
            dependents[dependency].append(task.id)
    ready = [task_id for task_id in ids if indegree[task_id] == 0]
    ordered: list[str] = []
    while ready:
        task_id = ready.pop(0)
        ordered.append(task_id)
        for dependent in dependents[task_id]:
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                ready.append(dependent)
    return tuple(ordered) if len(ordered) == len(ids) else None
