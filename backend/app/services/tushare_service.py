"""TushareService Protocol + RealTushareService.

8 接口对应 8 个 method(per spec § 3.1).
内部:cache → rate limit → client.call → cache set → return DataFrame.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

import pandas as pd
from dateutil.relativedelta import relativedelta

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

    # v0.8.5: 6 个新接口 (P0+P1 tool 扩展, ref spec § 4.6)
    async def get_daily_basic(
        self, *, ts_code: str, trade_date: str | None = None
    ) -> pd.DataFrame: ...
    async def get_pe_history(
        self, *, ts_code: str, years_back: int = 5, current_pe: float | None = None
    ) -> pd.DataFrame: ...
    async def get_forecast(self, *, ts_code: str, period: str | None = None) -> pd.DataFrame: ...
    async def get_dividend_history(self, *, ts_code: str, years_back: int = 5) -> pd.DataFrame: ...
    async def get_holder_change(self, *, ts_code: str, years_back: int = 2) -> pd.DataFrame: ...
    async def get_money_flow(
        self, *, ts_code: str, start_date: str, end_date: str
    ) -> pd.DataFrame: ...
    async def get_index_daily(
        self, *, ts_code: str, start_date: str, end_date: str
    ) -> pd.DataFrame: ...
    async def get_fund_nav(
        self, *, ts_code: str, start_date: str, end_date: str
    ) -> pd.DataFrame: ...
    async def get_fund_basic(self, *, ts_code: str) -> pd.DataFrame: ...
    async def get_stock_basic(self, *, ts_code: str) -> pd.DataFrame: ...
    async def get_sw_index_daily(self, *, index_code: str, trade_date: str) -> pd.DataFrame: ...

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

    async def _call_cached(
        self, api_name: str, params: dict[str, Any], fields: str | None = None
    ) -> pd.DataFrame:
        # fields 必须作为 client.call 的独立参数(→ 请求 body 顶层 "fields"),不能塞进 params:
        # Tushare 会忽略 params 里的未知键 fields,导致字段投影失效(返回全字段)。
        # fields 并入 cache key,避免"有投影 / 无投影"两种结果在同一 (api,params) 下串味。
        cache_params = params if fields is None else {**params, "__fields__": fields}
        cached = await self._cache.get(api_name, cache_params)
        if cached is not None:
            return cached
        await self._rl.acquire()
        df = await self._client.call(api_name, params, fields=fields)
        await self._cache.set(api_name, cache_params, df, ttl_s=classify_ttl(api_name))
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

    # ---------------------------------------------------------------------
    # v0.8.5 — 6 个新接口 (P0+P1 tool 扩展, ref spec § 4.6)
    # ---------------------------------------------------------------------

    @staticmethod
    def _today_yyyymmdd() -> str:
        return datetime.now(UTC).strftime("%Y%m%d")

    @staticmethod
    def _n_years_ago(n: int) -> str:
        # relativedelta avoids leap-year drift (5 days over 5 years vs timedelta(days=365*n)).
        return (datetime.now(UTC) - relativedelta(years=n)).strftime("%Y%m%d")

    async def get_daily_basic(self, *, ts_code: str, trade_date: str | None = None) -> pd.DataFrame:
        return await self._call_cached(
            "daily_basic",
            {"ts_code": ts_code, "trade_date": trade_date or self._today_yyyymmdd()},
        )

    async def get_pe_history(
        self, *, ts_code: str, years_back: int = 5, current_pe: float | None = None
    ) -> pd.DataFrame:
        """聚合历史 daily_basic 计算 PE 分位.

        实现:取近 N 年的 daily_basic.pe 分布,计算 current_pe 在分布中的 percentile.
        """
        end = self._today_yyyymmdd()
        start = self._n_years_ago(years_back)
        history = await self._call_cached(
            "daily_basic",
            {"ts_code": ts_code, "start_date": start, "end_date": end},
            fields="pe",
        )
        if current_pe is None:
            latest = await self._call_cached(
                "daily_basic", {"ts_code": ts_code, "trade_date": end}, fields="pe"
            )
            # 不能 silent fallback 0.0:那会让 percentile 算出"PE 处于 0% 分位",
            # 看起来像"史上最便宜"的伪买入信号.调用方必须显式处理空数据.
            if latest.empty or pd.isna(latest["pe"].iloc[0]):
                raise ValueError(
                    f"cannot resolve current_pe for {ts_code} on {end}: "
                    "latest daily_basic is empty or NaN"
                )
            current_pe = float(latest["pe"].iloc[0])
        pe_series = history["pe"].dropna().sort_values()
        n = len(pe_series)
        rank = int((pe_series < current_pe).sum())
        percentile = rank / max(n, 1)
        return pd.DataFrame(
            {
                "ts_code": [ts_code],
                "current_pe": [current_pe],
                "historical_percentile": [float(percentile)],
                "min_pe": [float(pe_series.min()) if n > 0 else 0.0],
                "max_pe": [float(pe_series.max()) if n > 0 else 0.0],
                "median_pe": [float(pe_series.median()) if n > 0 else 0.0],
            }
        )

    async def get_forecast(self, *, ts_code: str, period: str | None = None) -> pd.DataFrame:
        params: dict[str, Any] = {"ts_code": ts_code}
        if period:
            params["period"] = period
        return await self._call_cached("forecast", params)

    async def get_dividend_history(self, *, ts_code: str, years_back: int = 5) -> pd.DataFrame:
        # Tushare `dividend` 接口**没有** ann_date_start/ann_date_end 这类区间参数
        # (官方只有单值 ann_date / record_date / ex_date 等),原实现传它们会被静默忽略
        # → 实际拉回该股全量分红历史、years_back 完全失效(近 N 年统计口径全错)。
        # 改为仅按 ts_code 拉取,再在客户端按公告日 ann_date 裁剪近 years_back 年。
        start = self._n_years_ago(years_back)
        df = await self._call_cached("dividend", {"ts_code": ts_code})
        if not df.empty and "ann_date" in df.columns:
            df = df[df["ann_date"].notna() & (df["ann_date"].astype(str) >= start)]
        return df

    async def get_holder_change(self, *, ts_code: str, years_back: int = 2) -> pd.DataFrame:
        """股东户数变化 — wraps existing stk_holdernumber API with date range."""
        end = self._today_yyyymmdd()
        start = self._n_years_ago(years_back)
        return await self._call_cached(
            "stk_holdernumber",
            {"ts_code": ts_code, "start_date": start, "end_date": end},
        )

    async def get_money_flow(self, *, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return await self._call_cached(
            "moneyflow",
            {"ts_code": ts_code, "start_date": start_date, "end_date": end_date},
        )

    async def get_index_daily(
        self, *, ts_code: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        return await self._call_cached(
            "index_daily",  # tushare 真实 API
            {"ts_code": ts_code, "start_date": start_date, "end_date": end_date},
        )

    async def get_fund_nav(self, *, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return await self._call_cached(
            "fund_nav",
            {"ts_code": ts_code, "start_date": start_date, "end_date": end_date},
        )

    async def get_fund_basic(self, *, ts_code: str) -> pd.DataFrame:
        return await self._call_cached("fund_basic", {"ts_code": ts_code})

    async def get_stock_basic(self, *, ts_code: str) -> pd.DataFrame:
        # fields 投影:只取 ts_code,name,industry(减少传输量)
        return await self._call_cached(
            "stock_basic",
            {"ts_code": ts_code},
            fields="ts_code,name,industry",
        )

    async def get_sw_index_daily(self, *, index_code: str, trade_date: str) -> pd.DataFrame:
        # tushare sw_daily — 申万行业指数当日行情
        # 积分不足时降级使用 index_daily(通用行情);此处保持真实接口
        return await self._call_cached(
            "sw_daily",
            {"ts_code": index_code, "trade_date": trade_date},
        )

    async def aclose(self) -> None:
        await self._client.aclose()
