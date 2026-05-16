"""TushareBacktestAdapter — backtest 模式下的 tushare client wrapper.

spec § 4.5 决策 5:time-travel 数据控制 — 任何 tushare 调用都不能返回 ann_date /
trade_date > cut_off 的数据。本 adapter 通过两层防御实现:
  1. 调用 inner client 时强制注入 end_date <= cut_off 参数
  2. 对返回行做二次过滤(防御 inner 不老实)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol


class TushareClientProtocol(Protocol):
    """允许真 TushareClient 或 mock 都注入."""

    def income(self, **kwargs: Any) -> list[dict[str, Any]]: ...
    def daily(self, **kwargs: Any) -> list[dict[str, Any]]: ...
    def balancesheet(self, **kwargs: Any) -> list[dict[str, Any]]: ...
    def cashflow(self, **kwargs: Any) -> list[dict[str, Any]]: ...
    def anns(self, **kwargs: Any) -> list[dict[str, Any]]: ...


@dataclass
class TushareBacktestAdapter:
    """Wrap a tushare client, 注入 cut_off 限制到所有时间相关接口."""

    inner: TushareClientProtocol
    cut_off: date

    @property
    def _cut_off_str(self) -> str:
        """tushare 接受的日期格式: YYYYMMDD."""
        return self.cut_off.strftime("%Y%m%d")

    def fetch_income(self, ts_code: str, **extra: Any) -> list[dict[str, Any]]:
        """fetch 利润表, 自动加 end_date <= cut_off."""
        rows = self.inner.income(ts_code=ts_code, end_date=self._cut_off_str, **extra)
        return self._filter_by_ann_date(rows)

    def fetch_balancesheet(self, ts_code: str, **extra: Any) -> list[dict[str, Any]]:
        rows = self.inner.balancesheet(ts_code=ts_code, end_date=self._cut_off_str, **extra)
        return self._filter_by_ann_date(rows)

    def fetch_cashflow(self, ts_code: str, **extra: Any) -> list[dict[str, Any]]:
        rows = self.inner.cashflow(ts_code=ts_code, end_date=self._cut_off_str, **extra)
        return self._filter_by_ann_date(rows)

    def fetch_daily_kline(
        self, ts_code: str, start_date: str, **extra: Any
    ) -> list[dict[str, Any]]:
        """fetch 日 K, end_date 由 cut_off 限定."""
        rows = self.inner.daily(
            ts_code=ts_code, start_date=start_date, end_date=self._cut_off_str, **extra
        )
        return [r for r in rows if r.get("trade_date", "99999999") <= self._cut_off_str]

    def fetch_announcements(self, ts_code: str, **extra: Any) -> list[dict[str, Any]]:
        rows = self.inner.anns(ts_code=ts_code, end_date=self._cut_off_str, **extra)
        return self._filter_by_ann_date(rows)

    def _filter_by_ann_date(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """丢掉任何 ann_date > cut_off 的行(防御 inner 不老实)."""
        return [r for r in rows if r.get("ann_date", "99999999") <= self._cut_off_str]
