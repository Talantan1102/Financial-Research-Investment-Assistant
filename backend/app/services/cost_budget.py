"""CostBudget — cumulative cost tracking with fail-fast over-limit assertion.

Used by LLMService to abort an eval/nightly run BEFORE making a call that
would push cumulative cost over EVAL_COST_LIMIT_CNY (default 20).

Per Plan B contract additive rule: LLMService accepts cost_budget=None and
behaves as if budget tracking didn't exist.
"""

from __future__ import annotations

import os


class BudgetExceeded(RuntimeError):  # noqa: N818 — plan-mandated name used in public API
    """Raised when CostBudget.assert_under_limit() finds spent > limit."""


_DEFAULT_LIMIT_CNY: float = 20.0  # spec § 5


class CostBudget:
    def __init__(self, limit_cny: float) -> None:
        if limit_cny <= 0:
            raise ValueError(f"limit_cny must be > 0, got {limit_cny}")
        self._limit_cny = limit_cny
        self._spent_cny = 0.0

    @classmethod
    def from_env(cls) -> CostBudget:
        raw = os.environ.get("EVAL_COST_LIMIT_CNY")
        # C46: wrap parse so a malformed env var gives a context-rich error
        if raw is not None:
            try:
                limit = float(raw)
            except ValueError:
                raise ValueError(
                    f"EVAL_COST_LIMIT_CNY must be a numeric float, got {raw!r}"
                ) from None
        else:
            limit = _DEFAULT_LIMIT_CNY
        return cls(limit_cny=limit)

    @property
    def limit_cny(self) -> float:
        return self._limit_cny

    @property
    def spent_cny(self) -> float:
        return self._spent_cny

    @property
    def remaining_cny(self) -> float:
        return max(0.0, self._limit_cny - self._spent_cny)

    def track(self, cost_cny: float) -> None:
        if cost_cny < 0:
            raise ValueError(f"cost_cny must be non-negative, got {cost_cny}")
        self._spent_cny += cost_cny

    def assert_under_limit(self) -> None:
        if self._spent_cny > self._limit_cny:
            raise BudgetExceeded(
                f"cumulative cost ¥{self._spent_cny:.2f} exceeds limit ¥{self._limit_cny:.2f}"
            )
