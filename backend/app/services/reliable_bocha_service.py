"""ReliableBochaService — wraps BochaService inner with 4 reliability layers + retry.

Layers (in order):
  1. quota_counter pre-check (fail fast)
  2. cost_budget pre-check (Plan D's assert_under_limit)
  3. circuit_breaker.call(...)
     within breaker:
       4. rate_limiter.acquire (await)
       5. inner.search(...)
       6. retry on (BochaNetworkError, BochaServerError) up to max_retries
  7. on success: quota_counter.increment + cost_budget.track
"""

from __future__ import annotations

import asyncio
import random
from typing import Any

from app.services.bocha_errors import BochaNetworkError, BochaServerError
from app.services.circuit_breaker import CircuitBreaker
from app.services.cost_budget import CostBudget
from app.services.quota_counter import QuotaCounter
from app.services.rate_limiter import RateLimiter


class ReliableBochaService:
    """BochaService Protocol-compatible: provides .search(query, count) -> dict."""

    def __init__(
        self,
        *,
        inner: Any,  # BochaService Protocol-compatible (typically BochaClient)
        rate_limiter: RateLimiter,
        circuit_breaker: CircuitBreaker,
        quota_counter: QuotaCounter,
        cost_budget: CostBudget,
        per_call_cost_cny: float = 0.01,
        max_retries: int = 3,
    ) -> None:
        self._inner = inner
        self._rate_limiter = rate_limiter
        self._circuit_breaker = circuit_breaker
        self.quota_counter = quota_counter
        self._cost_budget = cost_budget
        self._per_call_cost_cny = per_call_cost_cny
        self._max_retries = max_retries
        self._base_delay_s = 1.0
        self._jitter_max_s = 0.2

    async def search(self, *, query: str, count: int) -> dict[str, Any]:
        # 1. quota pre-check (fail fast, no inner call)
        if self.quota_counter.would_exceed():
            raise RuntimeError(
                f"quota exceeded: used {self.quota_counter.used_this_month()} of "
                f"{self.quota_counter._monthly_limit} this month"
            )
        # 1b. cost budget pre-check via Plan D's assert_under_limit()
        # (raises BudgetExceeded if cumulative spend already > limit_cny)
        self._cost_budget.assert_under_limit()

        # 2-5. breaker → rate_limit → inner with retry
        async def _attempt() -> dict[str, Any]:
            await self._rate_limiter.acquire()
            return await self._do_with_retry(query=query, count=count)

        result = await self._circuit_breaker.call(_attempt)

        # 6. on success
        self.quota_counter.increment()
        self._cost_budget.track(self._per_call_cost_cny)
        return result

    async def _do_with_retry(self, *, query: str, count: int) -> dict[str, Any]:
        """Exponential backoff + jitter; only retries Network/Server errors."""
        last: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                return await self._inner.search(query=query, count=count)
            except (BochaNetworkError, BochaServerError) as e:
                last = e
                if attempt < self._max_retries - 1:
                    delay = self._base_delay_s * (2**attempt) + random.uniform(
                        0, self._jitter_max_s
                    )
                    await asyncio.sleep(delay)
                continue
        if last is None:
            raise RuntimeError("retry loop exited without exception (impossible)")
        raise last

    async def aclose(self) -> None:
        if hasattr(self._inner, "aclose"):
            await self._inner.aclose()
