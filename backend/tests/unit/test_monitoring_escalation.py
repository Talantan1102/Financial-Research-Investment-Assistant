"""Unit tests for EscalationCoordinator(三道闸)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.services.cost_budget import CostBudget
from app.services.monitoring.escalation import (
    EscalationCoordinator,
    EscalationStatus,
)
from app.services.monitoring.signal_rules.base import (
    MonitoringCustomer,
    SignalLevel,
    SignalResult,
)


@pytest.fixture
def customer() -> MonitoringCustomer:
    return MonitoringCustomer(id="c1", ts_code="x.SH", name="x", industry="x")


@pytest.fixture
def signals() -> list[SignalResult]:
    return [SignalResult(rule_name="cash_flow", level=SignalLevel.RED, explanation="x")]


def _fake_graph(deep_dive: str, cost: float = 0.5) -> MagicMock:
    fake = MagicMock()
    state = MagicMock()
    state.deep_dive_section = deep_dive
    state.cost_cny = cost
    fake.ainvoke = AsyncMock(return_value={"deep_dive_section": deep_dive, "cost_cny": cost})
    return fake


@pytest.mark.asyncio
async def test_success_path(customer, signals, tmp_path: Path) -> None:
    coord = EscalationCoordinator(
        graph=_fake_graph("deep dive content"),
        daily_budget=CostBudget(limit_cny=10.0),
        per_call_cap_cny=1.0,
        concurrent_limit=1,
        recent_dedup_check=lambda cid, d: False,
    )
    result = await coord.escalate(customer, signals, run_id="r1")
    assert result.status == EscalationStatus.SUCCESS
    assert result.deep_dive == "deep dive content"


@pytest.mark.asyncio
async def test_per_call_cap_exceeded(customer, signals) -> None:
    """单次 cost > cap → 标 budget_per_call_exceeded."""
    coord = EscalationCoordinator(
        graph=_fake_graph("x", cost=2.0),  # 超 1.0 cap
        daily_budget=CostBudget(limit_cny=10.0),
        per_call_cap_cny=1.0,
        concurrent_limit=1,
        recent_dedup_check=lambda cid, d: False,
    )
    result = await coord.escalate(customer, signals, run_id="r1")
    assert result.status == EscalationStatus.BUDGET_PER_CALL_EXCEEDED


@pytest.mark.asyncio
async def test_daily_dedup(customer, signals) -> None:
    coord = EscalationCoordinator(
        graph=_fake_graph("x"),
        daily_budget=CostBudget(limit_cny=10.0),
        per_call_cap_cny=1.0,
        concurrent_limit=1,
        recent_dedup_check=lambda cid, d: True,  # 已 dedup
    )
    result = await coord.escalate(customer, signals, run_id="r1")
    assert result.status == EscalationStatus.DAILY_DEDUP


@pytest.mark.asyncio
async def test_daily_budget_exceeded(customer, signals) -> None:
    budget = CostBudget(limit_cny=0.1)  # 极小预算
    budget.track(0.5)  # 已 spent 超 limit
    coord = EscalationCoordinator(
        graph=_fake_graph("x"),
        daily_budget=budget,
        per_call_cap_cny=1.0,
        concurrent_limit=1,
        recent_dedup_check=lambda cid, d: False,
    )
    result = await coord.escalate(customer, signals, run_id="r1")
    assert result.status == EscalationStatus.DAILY_BUDGET_EXCEEDED


@pytest.mark.asyncio
async def test_concurrent_serialization(customer, signals) -> None:
    """concurrent_limit=1 时,2 次并发应顺序执行."""
    fake_graph = MagicMock()
    call_log: list[float] = []

    async def slow_invoke(state):
        import time

        call_log.append(time.monotonic())
        await asyncio.sleep(0.05)
        return {"deep_dive_section": "x", "cost_cny": 0.1}

    fake_graph.ainvoke = slow_invoke

    coord = EscalationCoordinator(
        graph=fake_graph,
        daily_budget=CostBudget(limit_cny=10.0),
        per_call_cap_cny=1.0,
        concurrent_limit=1,
        recent_dedup_check=lambda cid, d: False,
    )

    await asyncio.gather(
        coord.escalate(customer, signals, run_id="r1"),
        coord.escalate(customer, signals, run_id="r2"),
    )
    # 第二次调用应等到第一次完成后才开始(间隔 ≥ 0.04)
    assert len(call_log) == 2
    assert call_log[1] - call_log[0] >= 0.04


@pytest.mark.asyncio
async def test_gate2_non_budget_error_propagates(customer, signals) -> None:
    """C21: Gate 2 只吞 BudgetExceeded;其他异常必须冒泡,不能伪装成 DAILY_BUDGET_EXCEEDED。"""

    class _BoomBudget:
        def assert_under_limit(self) -> None:
            raise ValueError("unexpected bug")

        def track(self, cost: float) -> None:  # pragma: no cover — never reached
            pass

    coord = EscalationCoordinator(
        graph=_fake_graph("x"),
        daily_budget=_BoomBudget(),  # type: ignore[arg-type]
        per_call_cap_cny=1.0,
        concurrent_limit=1,
        recent_dedup_check=lambda cid, d: False,
    )
    with pytest.raises(ValueError, match="unexpected bug"):
        await coord.escalate(customer, signals, run_id="r1")


@pytest.mark.asyncio
async def test_graph_failure_logged_and_marked_failed(
    customer, signals, caplog: pytest.LogCaptureFixture
) -> None:
    """C21: graph 失败 → FAILED + 留 exception 日志(不再静默吞掉,hard rules 4+5)。"""
    fake = MagicMock()
    fake.ainvoke = AsyncMock(side_effect=RuntimeError("graph boom"))
    coord = EscalationCoordinator(
        graph=fake,
        daily_budget=CostBudget(limit_cny=10.0),
        per_call_cap_cny=1.0,
        concurrent_limit=1,
        recent_dedup_check=lambda cid, d: False,
    )
    with caplog.at_level("ERROR"):
        result = await coord.escalate(customer, signals, run_id="r1")
    assert result.status == EscalationStatus.FAILED
    assert "graph boom" in (result.error or "")
    assert any("escalation failed" in r.message for r in caplog.records)
