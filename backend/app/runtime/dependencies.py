"""Task graph dependency validation and exact output-reference resolution."""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Mapping
from typing import Any

from app.runtime.tasks import Task, TaskGraph

_TASK_REFERENCE = re.compile(r"^\$task\.([A-Za-z0-9_-]+)\.output$")


def task_reference_id(value: str) -> str | None:
    match = _TASK_REFERENCE.fullmatch(value)
    return match.group(1) if match is not None else None


class DependencyResolver:
    def validate(self, graph: TaskGraph) -> tuple[str, ...]:
        ids = graph.task_ids
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate task id")
        known = set(ids)
        indegree = dict.fromkeys(ids, 0)
        dependents: dict[str, list[str]] = {task_id: [] for task_id in ids}
        for task in graph.tasks:
            for reference in self._references(task.inputs):
                if reference == task.id:
                    raise ValueError(f"task {task.id!r} cannot reference itself")
                if reference not in known:
                    raise ValueError(f"task {task.id!r} references missing task {reference!r}")
            if set(task.depends_on) & set(task.optional_depends_on):
                raise ValueError("task declares the same dependency as strong and optional")
            for dependency in (*task.depends_on, *task.optional_depends_on):
                if dependency == task.id:
                    raise ValueError(f"task {task.id!r} cannot depend on itself")
                if dependency not in known:
                    raise ValueError(f"task {task.id!r} depends on missing task {dependency!r}")
                indegree[task.id] += 1
                dependents[dependency].append(task.id)
        ready = deque(task_id for task_id in ids if indegree[task_id] == 0)
        ordered: list[str] = []
        while ready:
            task_id = ready.popleft()
            ordered.append(task_id)
            for dependent in dependents[task_id]:
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    ready.append(dependent)
        if len(ordered) != len(ids):
            raise ValueError("task dependency cycle detected")
        return tuple(ordered)

    def resolve_inputs(self, task: Task, outputs: Mapping[str, Any]) -> dict[str, Any]:
        resolved = self._resolve(task.inputs, outputs)
        assert isinstance(resolved, dict)
        return resolved

    def _references(self, value: Any) -> tuple[str, ...]:
        found: list[str] = []
        if isinstance(value, str):
            reference = task_reference_id(value)
            if reference is not None:
                found.append(reference)
        elif isinstance(value, Mapping):
            for nested in value.values():
                found.extend(self._references(nested))
        elif isinstance(value, (list, tuple)):
            for nested in value:
                found.extend(self._references(nested))
        return tuple(dict.fromkeys(found))

    def _resolve(self, value: Any, outputs: Mapping[str, Any]) -> Any:
        if isinstance(value, str):
            task_id = task_reference_id(value)
            if task_id is None:
                return value
            if task_id not in outputs:
                raise ValueError(f"output unavailable for task {task_id!r}")
            return outputs[task_id]
        if isinstance(value, dict):
            return {key: self._resolve(item, outputs) for key, item in value.items()}
        if isinstance(value, list):
            return [self._resolve(item, outputs) for item in value]
        if isinstance(value, tuple):
            return tuple(self._resolve(item, outputs) for item in value)
        return value
