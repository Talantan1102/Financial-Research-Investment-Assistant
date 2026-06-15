"""Unit tests for RealTushareService — uses fake client + cache + rate limiter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from app.services.rate_limiter import RateLimiter
from app.services.tushare_cache import TushareCache
from app.services.tushare_service import RealTushareService, TushareService


class FakeTushareClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def call(
        self, api_name: str, params: dict[str, Any], fields: str | None = None
    ) -> pd.DataFrame:
        self.calls.append((api_name, params))
        return pd.DataFrame({"ts_code": ["600519.SH"], "x": [1.0]})


@pytest.fixture
def cache(tmp_path: Path) -> TushareCache:
    return TushareCache(db_path=tmp_path / "cache.sqlite")


@pytest.fixture
def service(cache: TushareCache) -> tuple[RealTushareService, FakeTushareClient]:
    fake = FakeTushareClient()
    svc = RealTushareService(
        client=fake,  # type: ignore[arg-type]
        cache=cache,
        rate_limiter=RateLimiter(max_calls=10, window_s=60.0),
    )
    return svc, fake


@pytest.mark.asyncio
async def test_get_daily_calls_client_first_time(
    service: tuple[RealTushareService, FakeTushareClient],
) -> None:
    svc, fake = service
    df = await svc.get_daily(ts_code="600519.SH", start="20240501", end="20240502")
    assert len(df) == 1
    assert len(fake.calls) == 1
    assert fake.calls[0][0] == "daily"


@pytest.mark.asyncio
async def test_get_daily_uses_cache_second_time(
    service: tuple[RealTushareService, FakeTushareClient],
) -> None:
    svc, fake = service
    await svc.get_daily(ts_code="600519.SH", start="20240501", end="20240502")
    await svc.get_daily(ts_code="600519.SH", start="20240501", end="20240502")
    assert len(fake.calls) == 1  # 第二次不应再 call


@pytest.mark.parametrize(
    "method,api_name",
    [
        ("get_income", "income"),
        ("get_fina_indicator", "fina_indicator"),
        # Tushare Pro uses "balancesheet" (no underscore) for balance sheet
        ("get_balance_sheet", "balancesheet"),
        ("get_cashflow", "cashflow"),
        ("get_stk_holdernumber", "stk_holdernumber"),
        # Tushare Pro uses "anns_d" (not "anns") for daily announcements
        ("get_anns", "anns_d"),
    ],
)
@pytest.mark.asyncio
async def test_8_methods_dispatch_to_correct_api(
    service: tuple[RealTushareService, FakeTushareClient],
    method: str,
    api_name: str,
) -> None:
    svc, fake = service
    fn = getattr(svc, method)
    if api_name == "anns_d":
        await fn(ts_code="600519.SH", start="20240501", end="20240601")
    else:
        await fn(ts_code="600519.SH")
    assert fake.calls[-1][0] == api_name


@pytest.mark.asyncio
async def test_get_disclosure_date_dispatches(
    service: tuple[RealTushareService, FakeTushareClient],
) -> None:
    svc, fake = service
    await svc.get_disclosure_date(ts_code=None, start="20240501", end="20240601")
    assert fake.calls[-1][0] == "disclosure_date"


@pytest.mark.asyncio
async def test_get_trade_cal_dispatches(
    service: tuple[RealTushareService, FakeTushareClient],
) -> None:
    svc, fake = service
    await svc.get_trade_cal(start="20260101", end="20260131")
    assert fake.calls[-1][0] == "trade_cal"
    assert fake.calls[-1][1]["start_date"] == "20260101"
    assert fake.calls[-1][1]["end_date"] == "20260131"
    assert fake.calls[-1][1]["exchange"] == "SSE"


def test_protocol_runtime_check(
    cache: TushareCache,
) -> None:
    """isinstance(svc, TushareService) exercises @runtime_checkable structurally."""
    fake = FakeTushareClient()
    svc = RealTushareService(
        client=fake,  # type: ignore[arg-type]
        cache=cache,
        rate_limiter=RateLimiter(max_calls=10, window_s=60.0),
    )
    assert isinstance(svc, TushareService)


class _CountingRateLimiter:
    """Wraps RateLimiter to count acquire() calls — used to verify cache-hit skips RL."""

    def __init__(self, max_calls: int, window_s: float) -> None:
        self._inner = RateLimiter(max_calls=max_calls, window_s=window_s)
        self.acquire_count = 0

    async def acquire(self) -> None:
        self.acquire_count += 1
        await self._inner.acquire()


@pytest.mark.asyncio
async def test_cache_hit_skips_rate_limiter(cache: TushareCache) -> None:
    """Second call with same params must not invoke rate_limiter.acquire()."""
    fake = FakeTushareClient()
    rl = _CountingRateLimiter(max_calls=10, window_s=60.0)
    svc = RealTushareService(
        client=fake,  # type: ignore[arg-type]
        cache=cache,
        rate_limiter=rl,  # type: ignore[arg-type]
    )
    await svc.get_daily(ts_code="600519.SH", start="20240501", end="20240502")
    await svc.get_daily(ts_code="600519.SH", start="20240501", end="20240502")
    assert rl.acquire_count == 1  # cache hit → no second acquire
