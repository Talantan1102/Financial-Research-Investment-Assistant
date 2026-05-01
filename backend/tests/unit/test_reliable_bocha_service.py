"""L0 — ReliableBochaService coordinates 4 reliability layers + retry."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from app.services.bocha_errors import BochaNetworkError, BochaServerError
from app.services.circuit_breaker import CircuitBreaker, CircuitOpenError
from app.services.cost_budget import CostBudget
from app.services.quota_counter import QuotaCounter
from app.services.rate_limiter import RateLimiter
from app.services.reliable_bocha_service import ReliableBochaService


def _build(
    tmp_path: Path, *, retry_count: int = 3, fail_threshold: int = 3
) -> tuple[ReliableBochaService, AsyncMock]:
    inner = AsyncMock()
    inner.search = AsyncMock(return_value={"items": [{"title": "ok"}]})
    inner.aclose = AsyncMock()
    svc = ReliableBochaService(
        inner=inner,
        rate_limiter=RateLimiter(max_calls=100, window_s=1.0),
        circuit_breaker=CircuitBreaker(failure_threshold=fail_threshold, cooldown_s=0.1),
        quota_counter=QuotaCounter(db_path=tmp_path / "q.sqlite", name="t", monthly_limit=100),
        cost_budget=CostBudget(limit_cny=10.0),
        per_call_cost_cny=0.01,
        max_retries=retry_count,
    )
    return svc, inner


@pytest.mark.asyncio
async def test_happy_path_increments_counters(tmp_path: Path) -> None:
    svc, inner = _build(tmp_path)
    result = await svc.search(query="x", count=3)
    assert result["items"][0]["title"] == "ok"
    inner.search.assert_called_once_with(query="x", count=3)
    assert svc.quota_counter.used_this_month() == 1


@pytest.mark.asyncio
async def test_quota_exceeded_blocks(tmp_path: Path) -> None:
    svc, inner = _build(tmp_path)
    # Fill quota
    for _ in range(100):
        svc.quota_counter.increment()
    with pytest.raises(Exception, match="quota"):
        await svc.search(query="x", count=1)
    # inner not called
    inner.search.assert_not_called()


@pytest.mark.asyncio
async def test_retry_on_network_error(tmp_path: Path) -> None:
    svc, inner = _build(tmp_path, retry_count=3)
    inner.search = AsyncMock(
        side_effect=[
            BochaNetworkError("dns"),
            BochaNetworkError("dns"),
            {"items": [{"title": "recovered"}]},
        ]
    )
    svc._base_delay_s = 0.01
    result = await svc.search(query="x", count=1)
    assert result["items"][0]["title"] == "recovered"
    assert inner.search.call_count == 3


@pytest.mark.asyncio
async def test_retry_exhausted_raises(tmp_path: Path) -> None:
    svc, inner = _build(tmp_path, retry_count=2)
    inner.search = AsyncMock(side_effect=BochaNetworkError("dns"))
    svc._base_delay_s = 0.01
    with pytest.raises(BochaNetworkError):
        await svc.search(query="x", count=1)
    assert inner.search.call_count == 2  # 2 retries (max_retries=2)


@pytest.mark.asyncio
async def test_breaker_opens_after_threshold(tmp_path: Path) -> None:
    svc, inner = _build(tmp_path, retry_count=1, fail_threshold=2)
    inner.search = AsyncMock(side_effect=BochaServerError("500"))
    svc._base_delay_s = 0.01
    # First failure
    with pytest.raises(BochaServerError):
        await svc.search(query="x", count=1)
    # Second failure → opens breaker
    with pytest.raises(BochaServerError):
        await svc.search(query="x", count=1)
    # Third call short-circuits
    with pytest.raises(CircuitOpenError):
        await svc.search(query="x", count=1)
