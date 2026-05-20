"""Ground truth loader for backtest case prediction validation.

Phase 1: 仅占位 + 接口签名 (真实现 Phase 2 M4 prediction metric).
Phase 2 M4: 实现 fetch_post_cut_off_kline / fetch_post_cut_off_anns 等方法.

spec § 4.4 / § 5.1
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Protocol


class TushareReadOnlyProtocol(Protocol):
    """ground truth 用真 tushare(不限 cut_off, 因为是事后查)."""

    def daily(self, **kwargs: Any) -> list[dict[str, Any]]: ...
    def anns(self, **kwargs: Any) -> list[dict[str, Any]]: ...


@dataclass
class GroundTruthLoader:
    """加载 backtest case cut_off 之后的真实数据用于 M4 验证.

    Phase 1: 仅 stub, Phase 2 M4 实现具体方法.
    """

    inner: TushareReadOnlyProtocol

    def fetch_post_cut_off_kline(
        self,
        ts_code: str,
        cut_off: date,
        horizon_days: int = 90,
    ) -> list[dict[str, Any]]:
        """取 cut_off 之后 horizon_days 天的日 K (rows sorted ascending by trade_date — kline[-1] = latest day within horizon, T2.5 _direction_correct contract).

        用于 M4 prediction metric: cut_off 后股价方向 / 目标价命中检测。
        """
        start = (cut_off + timedelta(days=1)).strftime("%Y%m%d")
        end = (cut_off + timedelta(days=horizon_days)).strftime("%Y%m%d")
        rows = self.inner.daily(ts_code=ts_code, start_date=start, end_date=end)
        # tushare daily returns descending by default; sort ascending for callers that index kline[-1]
        rows = sorted(rows, key=lambda r: r.get("trade_date", ""))
        # missing trade_date defaults to "" — falls below `start` so row drops (correct
        # behavior in post-cut-off window; cf. Phase 1 TushareBacktestAdapter uses
        # "99999999" sentinel for pre-cut-off filter where missing = future = drop)
        return [r for r in rows if start <= r.get("trade_date", "") <= end]

    def fetch_post_cut_off_anns(
        self,
        ts_code: str,
        cut_off: date,
        horizon_days: int = 90,
    ) -> list[dict[str, Any]]:
        """取 cut_off 之后 horizon_days 天的公告.

        用于 M4 prediction metric: 风险 flag 真实发生率检测。
        """
        start = (cut_off + timedelta(days=1)).strftime("%Y%m%d")
        end = (cut_off + timedelta(days=horizon_days)).strftime("%Y%m%d")
        rows = self.inner.anns(ts_code=ts_code, start_date=start, end_date=end)
        # missing ann_date defaults to "" — falls below `start` so row drops (correct
        # behavior in post-cut-off window; cf. Phase 1 TushareBacktestAdapter uses
        # "99999999" sentinel for pre-cut-off filter where missing = future = drop)
        return [r for r in rows if start <= r.get("ann_date", "") <= end]
