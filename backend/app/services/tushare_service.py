"""TushareService Protocol + RealTushareService.

8 接口对应 8 个 method(per spec § 3.1).
内部:cache → rate limit → client.call → cache set → return DataFrame.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

import pandas as pd

from app.services.rate_limiter import RateLimiter
from app.services.tushare_cache import TushareCache, classify_ttl
from app.services.tushare_client import TushareClient


@runtime_checkable
class TushareService(Protocol):
    async def get_daily(self, *, ts_code: str, start: str, end: str) -> pd.DataFrame: ...
    async def get_income(self, *, ts_code: str, end_date: str | None = None) -> pd.DataFrame: ...
    async def get_fina_indicator(
        self, *, ts_code: str, end_date: str | None = None
    ) -> pd.DataFrame: ...
    async def get_balance_sheet(
        self, *, ts_code: str, end_date: str | None = None
    ) -> pd.DataFrame: ...
    async def get_cashflow(self, *, ts_code: str, end_date: str | None = None) -> pd.DataFrame: ...
    async def get_stk_holdernumber(
        self, *, ts_code: str, end_date: str | None = None
    ) -> pd.DataFrame: ...
    async def get_disclosure_date(
        self, *, ts_code: str | None, start: str, end: str
    ) -> pd.DataFrame: ...
    async def get_anns(self, *, ts_code: str, start: str, end: str) -> pd.DataFrame: ...
    # Mock implementations should override aclose() as a no-op or handle their own cleanup.
    async def aclose(self) -> None: ...


class RealTushareService:
    def __init__(
        self,
        *,
        client: TushareClient,
        cache: TushareCache,
        rate_limiter: RateLimiter,
    ) -> None:
        self._client = client
        self._cache = cache
        self._rl = rate_limiter

    async def _call_cached(self, api_name: str, params: dict[str, Any]) -> pd.DataFrame:
        cached = await self._cache.get(api_name, params)
        if cached is not None:
            return cached
        await self._rl.acquire()
        df = await self._client.call(api_name, params)
        await self._cache.set(api_name, params, df, ttl_s=classify_ttl(api_name))
        return df

    async def get_daily(self, *, ts_code: str, start: str, end: str) -> pd.DataFrame:
        return await self._call_cached(
            "daily", {"ts_code": ts_code, "start_date": start, "end_date": end}
        )

    async def get_income(self, *, ts_code: str, end_date: str | None = None) -> pd.DataFrame:
        params: dict[str, Any] = {"ts_code": ts_code}
        if end_date:
            params["end_date"] = end_date
        return await self._call_cached("income", params)

    async def get_fina_indicator(
        self, *, ts_code: str, end_date: str | None = None
    ) -> pd.DataFrame:
        params: dict[str, Any] = {"ts_code": ts_code}
        if end_date:
            params["end_date"] = end_date
        return await self._call_cached("fina_indicator", params)

    async def get_balance_sheet(self, *, ts_code: str, end_date: str | None = None) -> pd.DataFrame:
        params: dict[str, Any] = {"ts_code": ts_code}
        if end_date:
            params["end_date"] = end_date
        # Tushare Pro API name is "balancesheet" (no underscore)
        return await self._call_cached("balancesheet", params)

    async def get_cashflow(self, *, ts_code: str, end_date: str | None = None) -> pd.DataFrame:
        params: dict[str, Any] = {"ts_code": ts_code}
        if end_date:
            params["end_date"] = end_date
        return await self._call_cached("cashflow", params)

    async def get_stk_holdernumber(
        self, *, ts_code: str, end_date: str | None = None
    ) -> pd.DataFrame:
        params: dict[str, Any] = {"ts_code": ts_code}
        if end_date:
            params["end_date"] = end_date
        return await self._call_cached("stk_holdernumber", params)

    async def get_disclosure_date(
        self, *, ts_code: str | None, start: str, end: str
    ) -> pd.DataFrame:
        params: dict[str, Any] = {"start_date": start, "end_date": end}
        if ts_code:
            params["ts_code"] = ts_code
        return await self._call_cached("disclosure_date", params)

    async def get_anns(self, *, ts_code: str, start: str, end: str) -> pd.DataFrame:
        # Tushare Pro API name for daily announcements is "anns_d" (not "anns")
        return await self._call_cached(
            "anns_d", {"ts_code": ts_code, "start_date": start, "end_date": end}
        )

    async def aclose(self) -> None:
        await self._client.aclose()
