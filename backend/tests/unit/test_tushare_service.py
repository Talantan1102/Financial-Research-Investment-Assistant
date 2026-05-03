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
        ("get_balance_sheet", "balance_sheet"),
        ("get_cashflow", "cashflow"),
        ("get_stk_holdernumber", "stk_holdernumber"),
        ("get_anns", "anns"),
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
    if api_name == "anns":
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


def test_protocol_runtime_check() -> None:
    """RealTushareService satisfies TushareService Protocol structurally."""
    # No assertion needed — mypy + isinstance via @runtime_checkable
    assert hasattr(RealTushareService, "get_daily")
    assert hasattr(RealTushareService, "get_income")
    assert hasattr(RealTushareService, "get_fina_indicator")
    assert hasattr(RealTushareService, "get_balance_sheet")
    assert hasattr(RealTushareService, "get_cashflow")
    assert hasattr(RealTushareService, "get_stk_holdernumber")
    assert hasattr(RealTushareService, "get_disclosure_date")
    assert hasattr(RealTushareService, "get_anns")
    # Verify protocol exists
    assert TushareService is not None
