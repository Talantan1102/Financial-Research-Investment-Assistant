"""Deterministic assertion-engine contract tests for Task 3."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
from eval.chatloop.assertion_engine import AssertionEngine
from eval.chatloop.case_schema import AssertionSpec


@pytest.fixture
def engine() -> AssertionEngine:
    return AssertionEngine()


def passing_observation() -> dict[str, Any]:
    return {
        "run": {
            "status": "completed",
            "steps": ["plan", "answer"],
            "metadata": {"pause_reason": None},
            "approved": True,
        },
        "tools": {
            "called": ["get_quote", "check_permissions", "place_order"],
            "ledger": {"count": 3},
            "calls": None,
            "flags": [True, False],
        },
        "database": {
            "before": {
                "orders": {"count": 1, "ids": ["ord-1"]},
                "portfolio": {"cash": 1000, "note": None, "approved": True},
                "watchlist": {"symbols": ["600519", "000001"]},
            },
            "after": {
                "orders": {"count": 2, "ids": ["ord-1", "ord-2"]},
                "portfolio": {"cash": 1000, "note": None, "approved": True},
                "watchlist": {"symbols": ["600519", "000001"]},
            },
        },
        "answer": {
            "text": "Added it to the watchlist without promising returns.",
            "bullets": ["explain the current state", "explain the limit"],
        },
        "evidence": {
            "versions": {"code": "69a3d391", "policy": "2026.1"},
            "cost_latency": {"cost_usd": 0.02, "latency_ms": 321},
        },
        "judge": {"verdict": "supported", "confidence": "high"},
    }


def test_missing_database_path_is_agent_failure_not_harness_failure(
    engine: AssertionEngine,
) -> None:
    result = engine.evaluate(
        AssertionSpec(
            assertion_id="order-not-created",
            source="database",
            operator="equals",
            path="after.orders.count",
            expected=0,
        ),
        observation={"database": {"after": {}}},
    )

    assert result.assertion_id == "order-not-created"
    assert result.passed is False
    assert result.kind == "assertion_failed"


def test_missing_database_snapshot_invalidates_evidence(engine: AssertionEngine) -> None:
    result = engine.evaluate(
        AssertionSpec(
            assertion_id="order-count",
            source="database",
            operator="equals",
            path="after.orders.count",
            expected=0,
        ),
        observation={},
    )

    assert result.passed is False
    assert result.kind == "invalid_evidence"


def test_top_level_null_source_is_invalid_evidence(engine: AssertionEngine) -> None:
    result = engine.evaluate(
        AssertionSpec(
            assertion_id="tool-calls-exist",
            source="tools",
            operator="exists",
            path="calls",
        ),
        observation={"tools": None},
    )

    assert result.passed is False
    assert result.kind == "invalid_evidence"


def test_present_nested_null_path_does_not_count_as_usable_evidence(
    engine: AssertionEngine,
) -> None:
    result = engine.evaluate(
        AssertionSpec(
            assertion_id="tool-calls-exist",
            source="tools",
            operator="exists",
            path="calls",
        ),
        observation=passing_observation(),
    )

    assert result.passed is False
    assert result.kind == "assertion_failed"
    assert result.actual is None


def test_list_shaped_source_is_not_invalid_by_itself(engine: AssertionEngine) -> None:
    result = engine.evaluate(
        AssertionSpec(
            assertion_id="tool-order",
            source="tools",
            operator="ordered_subsequence",
            path="",
            expected=["get_quote", "place_order"],
        ),
        observation={"tools": ["get_quote", "check_permissions", "place_order"]},
    )

    assert result.passed is True
    assert result.kind == "passed"


def test_present_null_value_is_not_treated_as_missing(engine: AssertionEngine) -> None:
    exists_result = engine.evaluate(
        AssertionSpec(
            assertion_id="portfolio-note-exists",
            source="database",
            operator="exists",
            path="before.portfolio.note",
        ),
        observation=passing_observation(),
    )
    absent_result = engine.evaluate(
        AssertionSpec(
            assertion_id="portfolio-note-absent",
            source="database",
            operator="absent",
            path="before.portfolio.note",
        ),
        observation=passing_observation(),
    )
    equals_none_result = engine.evaluate(
        AssertionSpec(
            assertion_id="portfolio-note-null",
            source="database",
            operator="equals",
            path="before.portfolio.note",
            expected=None,
            policy_id="DATA-SOURCE",
            severity="C2",
        ),
        observation=passing_observation(),
    )

    assert exists_result.passed is False
    assert absent_result.passed is False
    assert equals_none_result.passed is True
    assert equals_none_result.actual is None
    assert equals_none_result.expected is None
    assert equals_none_result.policy_id == "DATA-SOURCE"
    assert equals_none_result.severity == "C2"


@pytest.mark.parametrize("value", ["", [], {}])
def test_exists_rejects_empty_values(engine: AssertionEngine, value: object) -> None:
    result = engine.evaluate(
        AssertionSpec(
            assertion_id="non-empty-answer",
            source="answer",
            operator="exists",
            path="text",
        ),
        observation={"answer": {"text": value}},
    )

    assert result.passed is False
    assert result.kind == "assertion_failed"


def test_unchanged_requires_before_and_after_snapshots(engine: AssertionEngine) -> None:
    result = engine.evaluate(
        AssertionSpec(
            assertion_id="cash-unchanged",
            source="database",
            operator="unchanged",
            path="portfolio.cash",
        ),
        observation={"database": {"after": {"portfolio": {"cash": 1000}}}},
    )

    assert result.passed is False
    assert result.kind == "invalid_evidence"


def test_unchanged_treats_missing_business_path_as_assertion_failure(
    engine: AssertionEngine,
) -> None:
    result = engine.evaluate(
        AssertionSpec(
            assertion_id="cash-unchanged",
            source="database",
            operator="unchanged",
            path="portfolio.cash",
        ),
        observation={"database": {"before": {}, "after": {}}},
    )

    assert result.passed is False
    assert result.kind == "assertion_failed"


@pytest.mark.parametrize(
    ("assertion", "mutate"),
    [
        (
            AssertionSpec(
                assertion_id="equals-pass",
                source="run",
                operator="equals",
                path="status",
                expected="completed",
            ),
            lambda observation: observation["run"].__setitem__("status", "failed"),
        ),
        (
            AssertionSpec(
                assertion_id="not-equals-pass",
                source="run",
                operator="not_equals",
                path="status",
                expected="pending",
            ),
            lambda observation: observation["run"].__setitem__("status", "pending"),
        ),
        (
            AssertionSpec(
                assertion_id="exists-pass",
                source="answer",
                operator="exists",
                path="text",
            ),
            lambda observation: observation["answer"].pop("text"),
        ),
        (
            AssertionSpec(
                assertion_id="absent-pass",
                source="tools",
                operator="absent",
                path="deprecated_call",
            ),
            lambda observation: observation["tools"].__setitem__("deprecated_call", True),
        ),
        (
            AssertionSpec(
                assertion_id="unchanged-pass",
                source="database",
                operator="unchanged",
                path="portfolio.cash",
            ),
            lambda observation: observation["database"]["after"]["portfolio"].__setitem__(
                "cash", 999
            ),
        ),
        (
            AssertionSpec(
                assertion_id="contains-pass",
                source="answer",
                operator="contains",
                path="text",
                expected="watchlist",
            ),
            lambda observation: observation["answer"].__setitem__("text", "Order placed."),
        ),
        (
            AssertionSpec(
                assertion_id="not-contains-pass",
                source="answer",
                operator="not_contains",
                path="text",
                expected="guaranteed return",
            ),
            lambda observation: observation["answer"].__setitem__(
                "text", "This has a guaranteed return."
            ),
        ),
        (
            AssertionSpec(
                assertion_id="count-equals-pass",
                source="tools",
                operator="count_equals",
                path="called",
                expected=3,
            ),
            lambda observation: observation["tools"]["called"].append("cancel_order"),
        ),
        (
            AssertionSpec(
                assertion_id="ordered-subsequence-pass",
                source="tools",
                operator="ordered_subsequence",
                path="called",
                expected=["get_quote", "place_order"],
            ),
            lambda observation: observation["tools"].__setitem__(
                "called", ["place_order", "get_quote", "check_permissions"]
            ),
        ),
        (
            AssertionSpec(
                assertion_id="subset-pass",
                source="database",
                operator="subset",
                path="after.watchlist.symbols",
                expected=["600519"],
            ),
            lambda observation: observation["database"]["after"]["watchlist"].__setitem__(
                "symbols", ["000001"]
            ),
        ),
    ],
)
def test_each_operator_has_passing_and_single_mutation_failing_observation(
    engine: AssertionEngine,
    assertion: AssertionSpec,
    mutate: Any,
) -> None:
    observation = passing_observation()
    passing = engine.evaluate(assertion, observation=observation)

    mutated_observation = deepcopy(observation)
    mutate(mutated_observation)
    failing = engine.evaluate(assertion, observation=mutated_observation)

    assert passing.passed is True, assertion.assertion_id
    assert passing.kind == "passed", assertion.assertion_id
    assert failing.passed is False, assertion.assertion_id
    assert failing.kind == "assertion_failed", assertion.assertion_id


def test_equals_treats_bool_and_int_as_distinct(engine: AssertionEngine) -> None:
    result = engine.evaluate(
        AssertionSpec(
            assertion_id="strict-bool-equals",
            source="run",
            operator="equals",
            path="approved",
            expected=1,
        ),
        observation=passing_observation(),
    )

    assert result.passed is False


def test_not_equals_treats_bool_and_int_as_distinct(engine: AssertionEngine) -> None:
    result = engine.evaluate(
        AssertionSpec(
            assertion_id="strict-bool-not-equals",
            source="run",
            operator="not_equals",
            path="approved",
            expected=1,
        ),
        observation=passing_observation(),
    )

    assert result.passed is True


def test_unchanged_treats_bool_and_int_as_distinct(engine: AssertionEngine) -> None:
    observation = passing_observation()
    observation["database"]["after"]["portfolio"]["approved"] = 1

    result = engine.evaluate(
        AssertionSpec(
            assertion_id="strict-bool-unchanged",
            source="database",
            operator="unchanged",
            path="portfolio.approved",
        ),
        observation=observation,
    )

    assert result.passed is False
    assert result.kind == "assertion_failed"


def test_contains_treats_bool_and_int_membership_as_distinct(engine: AssertionEngine) -> None:
    result = engine.evaluate(
        AssertionSpec(
            assertion_id="strict-bool-contains",
            source="tools",
            operator="contains",
            path="flags",
            expected=1,
        ),
        observation=passing_observation(),
    )

    assert result.passed is False


def test_count_equals_rejects_bool_expected_value(engine: AssertionEngine) -> None:
    result = engine.evaluate(
        AssertionSpec(
            assertion_id="strict-bool-count",
            source="tools",
            operator="count_equals",
            path="called",
            expected=True,
        ),
        observation=passing_observation(),
    )

    assert result.passed is False


def test_ordered_subsequence_treats_bool_and_int_items_as_distinct(
    engine: AssertionEngine,
) -> None:
    result = engine.evaluate(
        AssertionSpec(
            assertion_id="strict-bool-subsequence",
            source="tools",
            operator="ordered_subsequence",
            path="flags",
            expected=[1],
        ),
        observation=passing_observation(),
    )

    assert result.passed is False


def test_subset_treats_bool_and_int_values_as_distinct(engine: AssertionEngine) -> None:
    result = engine.evaluate(
        AssertionSpec(
            assertion_id="strict-bool-subset",
            source="database",
            operator="subset",
            path="before.portfolio",
            expected={"approved": 1},
        ),
        observation=passing_observation(),
    )

    assert result.passed is False


def test_empty_ordered_subsequence_explicitly_passes(engine: AssertionEngine) -> None:
    result = engine.evaluate(
        AssertionSpec(
            assertion_id="empty-subsequence",
            source="tools",
            operator="ordered_subsequence",
            path="called",
            expected=[],
        ),
        observation=passing_observation(),
    )

    assert result.passed is True
