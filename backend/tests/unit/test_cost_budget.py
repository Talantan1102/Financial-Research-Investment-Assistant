"""L0 — CostBudget accumulation + over-limit fail-fast."""

import pytest
from app.services.cost_budget import BudgetExceeded, CostBudget


def test_under_limit_accumulates() -> None:
    b = CostBudget(limit_cny=1.0)
    b.track(0.3)
    b.track(0.4)
    assert b.spent_cny == pytest.approx(0.7)
    assert b.remaining_cny == pytest.approx(0.3)


def test_at_limit_does_not_raise() -> None:
    """Exactly at limit is fine; over is not."""
    b = CostBudget(limit_cny=1.0)
    b.track(1.0)
    b.assert_under_limit()  # equals, not exceeds


def test_over_limit_assert_raises() -> None:
    b = CostBudget(limit_cny=1.0)
    b.track(0.5)
    b.track(0.6)
    with pytest.raises(BudgetExceeded, match="1.10"):
        b.assert_under_limit()


def test_track_then_assert_pattern() -> None:
    """Caller pattern: chat(...) → track(cost) → assert_under_limit() before next call."""
    b = CostBudget(limit_cny=0.5)
    b.track(0.4)
    b.assert_under_limit()
    b.track(0.2)
    with pytest.raises(BudgetExceeded):
        b.assert_under_limit()


def test_negative_track_rejected() -> None:
    b = CostBudget(limit_cny=1.0)
    with pytest.raises(ValueError, match="non-negative"):
        b.track(-0.01)


def test_default_limit_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVAL_COST_LIMIT_CNY", "5.0")
    b = CostBudget.from_env()
    assert b.limit_cny == 5.0


def test_from_env_default_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EVAL_COST_LIMIT_CNY", raising=False)
    b = CostBudget.from_env()
    assert b.limit_cny == 20.0  # spec § 5 default
