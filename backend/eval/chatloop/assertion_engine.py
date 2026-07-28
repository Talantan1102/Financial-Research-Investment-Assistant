"""Deterministic assertion evaluation over structured trial observations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from eval.chatloop.case_schema import AssertionSpec

__all__ = [
    "AssertionEngine",
    "AssertionResult",
    "AssertionResultKind",
]

_MISSING = object()


class AssertionResultKind(StrEnum):
    PASSED = "passed"
    ASSERTION_FAILED = "assertion_failed"
    INVALID_EVIDENCE = "invalid_evidence"


@dataclass(frozen=True, slots=True)
class AssertionResult:
    """Typed outcome of evaluating one AssertionSpec."""

    assertion_id: str
    passed: bool
    kind: AssertionResultKind
    actual: Any
    expected: Any
    policy_id: str | None
    severity: str | None
    source: str
    path: str


@dataclass(frozen=True, slots=True)
class _LookupResult:
    found: bool
    value: Any


class AssertionEngine:
    """Evaluate AssertionSpec objects against a trial observation bundle."""

    def evaluate(
        self,
        assertion: AssertionSpec,
        *,
        observation: Mapping[str, Any],
    ) -> AssertionResult:
        if assertion.source not in observation:
            return self._result(
                assertion,
                passed=False,
                kind=AssertionResultKind.INVALID_EVIDENCE,
                actual="<missing_source>",
            )

        source_value = observation[assertion.source]
        if source_value is None:
            return self._result(
                assertion,
                passed=False,
                kind=AssertionResultKind.INVALID_EVIDENCE,
                actual="<null_source>",
            )
        if assertion.operator == "unchanged":
            return self._evaluate_unchanged(assertion, source_value)

        resolved = self._lookup(source_value, assertion.path)
        if assertion.operator == "absent":
            return self._result(
                assertion,
                passed=not resolved.found,
                kind=AssertionResultKind.PASSED
                if not resolved.found
                else AssertionResultKind.ASSERTION_FAILED,
                actual=None if not resolved.found else resolved.value,
            )
        if not resolved.found:
            return self._result(
                assertion,
                passed=False,
                kind=AssertionResultKind.ASSERTION_FAILED,
                actual="<missing_path>",
            )

        passed = self._compare(assertion.operator, resolved.value, assertion.expected)
        return self._result(
            assertion,
            passed=passed,
            kind=AssertionResultKind.PASSED if passed else AssertionResultKind.ASSERTION_FAILED,
            actual=resolved.value,
        )

    def _evaluate_unchanged(self, assertion: AssertionSpec, source_value: Any) -> AssertionResult:
        if not isinstance(source_value, Mapping):
            return self._result(
                assertion,
                passed=False,
                kind=AssertionResultKind.INVALID_EVIDENCE,
                actual="<invalid_source>",
            )
        if "before" not in source_value or "after" not in source_value:
            return self._result(
                assertion,
                passed=False,
                kind=AssertionResultKind.INVALID_EVIDENCE,
                actual="<missing_before_after>",
            )

        before = self._lookup(source_value["before"], assertion.path)
        after = self._lookup(source_value["after"], assertion.path)
        if not before.found or not after.found:
            return self._result(
                assertion,
                passed=False,
                kind=AssertionResultKind.ASSERTION_FAILED,
                actual={
                    "before": None if not before.found else before.value,
                    "after": None if not after.found else after.value,
                },
            )

        actual = {"before": before.value, "after": after.value}
        passed = self._strict_equal(before.value, after.value)
        return self._result(
            assertion,
            passed=passed,
            kind=AssertionResultKind.PASSED if passed else AssertionResultKind.ASSERTION_FAILED,
            actual=actual,
        )

    def _result(
        self,
        assertion: AssertionSpec,
        *,
        passed: bool,
        kind: AssertionResultKind,
        actual: Any,
    ) -> AssertionResult:
        return AssertionResult(
            assertion_id=assertion.assertion_id,
            passed=passed,
            kind=kind,
            actual=actual,
            expected=assertion.expected,
            policy_id=assertion.policy_id,
            severity=assertion.severity,
            source=assertion.source,
            path=assertion.path,
        )

    def _compare(self, operator: str, actual: Any, expected: Any) -> bool:
        if operator == "equals":
            return self._strict_equal(actual, expected)
        if operator == "not_equals":
            return not self._strict_equal(actual, expected)
        if operator == "exists":
            return True
        if operator == "contains":
            return self._contains(actual, expected)
        if operator == "not_contains":
            return not self._contains(actual, expected)
        if operator == "count_equals":
            if isinstance(expected, bool):
                return False
            try:
                return len(actual) == expected
            except TypeError:
                return False
        if operator == "ordered_subsequence":
            return self._ordered_subsequence(actual, expected)
        if operator == "subset":
            return self._subset(actual, expected)
        raise ValueError(f"unsupported operator: {operator}")

    def _lookup(self, source_value: Any, path: str) -> _LookupResult:
        if path == "":
            return _LookupResult(found=True, value=source_value)
        current = source_value
        for segment in path.split("."):
            if isinstance(current, Mapping):
                if segment not in current:
                    return _LookupResult(found=False, value=_MISSING)
                current = current[segment]
                continue
            if isinstance(current, Sequence) and not isinstance(current, (str, bytes, bytearray)):
                if not segment.isdigit():
                    return _LookupResult(found=False, value=_MISSING)
                index = int(segment)
                if index < 0 or index >= len(current):
                    return _LookupResult(found=False, value=_MISSING)
                current = current[index]
                continue
            return _LookupResult(found=False, value=_MISSING)
        return _LookupResult(found=True, value=current)

    def _contains(self, actual: Any, expected: Any) -> bool:
        if isinstance(actual, Mapping):
            return expected in actual
        if isinstance(actual, str):
            return expected in actual
        if isinstance(actual, (list, tuple, set, frozenset)):
            return any(self._strict_equal(item, expected) for item in actual)
        return False

    def _ordered_subsequence(self, actual: Any, expected: Any) -> bool:
        if not isinstance(actual, Sequence) or isinstance(actual, (str, bytes, bytearray)):
            return False
        if not isinstance(expected, Sequence) or isinstance(expected, (str, bytes, bytearray)):
            return False
        if len(expected) == 0:
            return True
        index = 0
        for item in actual:
            if index < len(expected) and self._strict_equal(item, expected[index]):
                index += 1
        return index == len(expected)

    def _subset(self, actual: Any, expected: Any) -> bool:
        if isinstance(actual, Mapping):
            if not isinstance(expected, Mapping):
                return False
            return all(
                key in actual and self._strict_equal(actual[key], value)
                for key, value in expected.items()
            )
        if isinstance(actual, str):
            if isinstance(expected, str):
                return expected in actual
            return False
        if isinstance(actual, (bytes, bytearray)):
            if isinstance(expected, (bytes, bytearray)):
                return expected in actual
            return False
        if isinstance(actual, (Sequence, set, frozenset)):
            if isinstance(expected, Sequence) and not isinstance(expected, (str, bytes, bytearray)):
                return all(
                    any(self._strict_equal(candidate, item) for candidate in actual)
                    for item in expected
                )
            return any(self._strict_equal(candidate, expected) for candidate in actual)
        return False

    def _strict_equal(self, actual: Any, expected: Any) -> bool:
        if isinstance(actual, bool) or isinstance(expected, bool):
            return isinstance(actual, bool) and isinstance(expected, bool) and actual is expected
        if isinstance(actual, Mapping) and isinstance(expected, Mapping):
            if set(actual) != set(expected):
                return False
            return all(self._strict_equal(actual[key], expected[key]) for key in actual)
        if (
            isinstance(actual, Sequence)
            and isinstance(expected, Sequence)
            and not isinstance(actual, (str, bytes, bytearray))
            and not isinstance(expected, (str, bytes, bytearray))
        ):
            if len(actual) != len(expected):
                return False
            return all(
                self._strict_equal(actual_item, expected_item)
                for actual_item, expected_item in zip(actual, expected, strict=True)
            )
        return actual == expected
