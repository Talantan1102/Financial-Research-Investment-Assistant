"""Deterministic assertion-operator contract tests for business eval trials."""

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
        },
        "tools": {
            "called": ["get_quote", "check_permissions", "place_order"],
            "ledger": {"count": 3},
        },
        "database": {
            "before": {
                "orders": {"count": 1, "ids": ["ord-1"]},
                "portfolio": {"cash": 1000, "note": None},
                "watchlist": {"symbols": ["600519", "000001"]},
            },
            "after": {
                "orders": {"count": 2, "ids": ["ord-1", "ord-2"]},
                "portfolio": {"cash": 1000, "note": None},
                "watchlist": {"symbols": ["600519", "000001"]},
            },
        },
        "answer": {
            "text": "已加入自选，但没有承诺收益。",
            "bullets": ["先解释现状", "再说明限制"],
        },
        "evidence": {
            "versions": {"code": "69a3d391", "policy": "2026.1"},
            "cost_latency": {"cost_usd": 0.02, "latency_ms": 321},
        },
        "judge": {
            "verdict": "supported",
            "confidence": "high",
        },
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

    assert exists_result.passed is True
    assert absent_result.passed is False
    assert equals_none_result.passed is True
    assert equals_none_result.actual is None
    assert equals_none_result.expected is None
    assert equals_none_result.policy_id == "DATA-SOURCE"
    assert equals_none_result.severity == "C2"


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
                expected="自选",
            ),
            lambda observation: observation["answer"].__setitem__("text", "已完成下单"),
        ),
        (
            AssertionSpec(
                assertion_id="not-contains-pass",
                source="answer",
                operator="not_contains",
                path="text",
                expected="保证收益",
            ),
            lambda observation: observation["answer"].__setitem__("text", "这次我保证收益。"),
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
