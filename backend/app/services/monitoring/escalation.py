"""EscalationCoordinator — 三道闸 + ResearchGraph 调用 for red alerts."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import date
from enum import StrEnum
from typing import Any

from pydantic import BaseModel

from app.services.cost_budget import CostBudget
from app.services.monitoring.signal_rules.base import (
    MonitoringCustomer,
    SignalResult,
)


class EscalationStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    BUDGET_PER_CALL_EXCEEDED = "budget_per_call_exceeded"
    DAILY_BUDGET_EXCEEDED = "daily_budget_exceeded"
    DAILY_DEDUP = "daily_dedup"


class EscalationResult(BaseModel):
    status: EscalationStatus
    deep_dive: str | None = None
    cost_cny: float = 0.0
    error: str | None = None


class EscalationCoordinator:
    def __init__(
        self,
        graph: Any,  # compiled LangGraph
        daily_budget: CostBudget,
        per_call_cap_cny: float = 1.0,
        concurrent_limit: int = 1,
        recent_dedup_check: Callable[[str, date], bool] = lambda cid, d: False,
    ) -> None:
        self._graph = graph
        self._daily_budget = daily_budget
        self._per_call_cap = per_call_cap_cny
        self._semaphore = asyncio.Semaphore(concurrent_limit)
        self._recent_dedup = recent_dedup_check

    async def escalate(
        self,
        customer: MonitoringCustomer,
        signals: list[SignalResult],
        run_id: str,
    ) -> EscalationResult:
        # Gate 1: daily dedup
        if self._recent_dedup(customer.id, date.today()):
            return EscalationResult(status=EscalationStatus.DAILY_DEDUP)

        # Gate 2: daily budget
        try:
            self._daily_budget.assert_under_limit()
        except Exception:
            return EscalationResult(status=EscalationStatus.DAILY_BUDGET_EXCEEDED)

        # Gate 3: concurrent limit (semaphore serializes simultaneous calls)
        async with self._semaphore:
            try:
                state = {
                    "user_id": "monitoring",
                    "session_id": customer.id,
                    "user_message": f"alert_deep_dive for {customer.name}",
                    "request_id": run_id,
                    "mode": "alert_deep_dive",
                    "alert_signals": signals,
                }
                result = await self._graph.ainvoke(state)
                cost = float(result.get("cost_cny", 0.0))
                deep_dive = result.get("deep_dive_section")

                # Gate 4: per-call cap (post-hoc, after pipeline ran)
                if cost > self._per_call_cap:
                    self._daily_budget.track(cost)
                    return EscalationResult(
                        status=EscalationStatus.BUDGET_PER_CALL_EXCEEDED,
                        cost_cny=cost,
                    )

                self._daily_budget.track(cost)
                return EscalationResult(
                    status=EscalationStatus.SUCCESS,
                    deep_dive=deep_dive,
                    cost_cny=cost,
                )
            except Exception as exc:
                return EscalationResult(status=EscalationStatus.FAILED, error=str(exc))
