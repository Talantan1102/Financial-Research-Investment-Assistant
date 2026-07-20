from __future__ import annotations

import json

import pytest
from app.runtime.dependencies import DependencyResolver
from app.runtime.models import CapabilityDefinition, CapabilityType, RiskLevel
from app.runtime.tasks import Task, TaskBuilder, TaskGraph
from app.services.llm_step import StepToolCall


def call(name: str, *, call_id: str, args: dict | None = None) -> StepToolCall:
    return StepToolCall(id=call_id, name=name, arguments=json.dumps(args or {}))


def definition(name: str, group: str | None = None) -> CapabilityDefinition:
    return CapabilityDefinition(
        name=name,
        type=CapabilityType.DATA_TOOL,
        input_schema={},
        output_schema={},
        minimum_risk=RiskLevel.LOW,
        read_only=True,
        idempotent=True,
        default_timeout_s=1,
        max_attempts=1,
        concurrency_group=group,
    )


def test_builder_strips_reserved_metadata_from_step_tool_call_inputs() -> None:
    graph = TaskBuilder().build(
        [
            call("quote", call_id="provider-call", args={"symbol": "X"}),
            call(
                "news",
                call_id="provider-call-2",
                args={
                    "__task_id": "news-task",
                    "__depends_on": ["provider-call"],
                    "__optional_depends_on": [],
                    "symbol": "X",
                },
            ),
        ]
    )

    assert graph.get("news-task").inputs == {"symbol": "X"}
    assert graph.get("news-task").depends_on == ("provider-call",)


def test_result_reference_adds_dependency_and_resolves_recursively() -> None:
    graph = TaskBuilder().build(
        [
            call("quote", call_id="quote"),
            call(
                "news",
                call_id="news",
                args={"quote": "$task.quote.output", "nested": ["$task.quote.output"]},
            ),
        ]
    )
    resolver = DependencyResolver()

    assert graph.get("news").depends_on == ("quote",)
    assert resolver.validate(graph) == ("quote", "news")
    assert resolver.resolve_inputs(graph.get("news"), {"quote": {"price": 10}}) == {
        "quote": {"price": 10},
        "nested": [{"price": 10}],
    }


def test_plain_calls_are_parallel_but_concurrency_group_is_serialized() -> None:
    definitions = {
        "db-a": definition("db-a", "db"),
        "network": definition("network"),
        "db-b": definition("db-b", "db"),
    }
    graph = TaskBuilder(definitions).build(
        [
            call("db-a", call_id="a"),
            call("network", call_id="b"),
            call("db-b", call_id="c"),
        ]
    )

    assert graph.get("a").depends_on == ()
    assert graph.get("b").depends_on == ()
    assert graph.get("c").depends_on == ("a",)


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ({"__depends_on": ["missing"]}, "missing"),
        ({"__depends_on": ["self"]}, "itself"),
        ({"x": "$task.previous.output"}, "previous"),
    ],
)
def test_invalid_graphs_are_rejected(args: dict, message: str) -> None:
    graph = TaskBuilder().build([call("tool", call_id="self", args=args)])
    with pytest.raises(ValueError, match=message):
        DependencyResolver().validate(graph)


def test_resolver_rejects_cycle_and_strong_optional_overlap() -> None:
    resolver = DependencyResolver()
    cyclic = TaskGraph(
        tasks=(
            Task(id="a", capability="x", inputs={}, depends_on=("b",)),
            Task(id="b", capability="x", inputs={}, depends_on=("a",)),
        )
    )
    overlap = TaskGraph(
        tasks=(
            Task(id="a", capability="x", inputs={}),
            Task(
                id="b",
                capability="x",
                inputs={},
                depends_on=("a",),
                optional_depends_on=("a",),
            ),
        )
    )

    with pytest.raises(ValueError, match="cycle"):
        resolver.validate(cyclic)
    with pytest.raises(ValueError, match="strong and optional"):
        resolver.validate(overlap)
