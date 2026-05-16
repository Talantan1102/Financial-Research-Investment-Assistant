"""Ground truth loader for backtest case prediction validation.

Phase 1: 仅占位 + 接口签名 (真实现 Phase 2 M4 prediction metric).
Phase 2 M4: 实现 fetch_post_cut_off_kline / fetch_post_cut_off_anns 等方法.

spec § 4.4 / § 5.1
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
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
        """Phase 2 M4: 取 cut_off 之后 horizon_days 天的日 K."""
        raise NotImplementedError("Phase 2 M4 prediction metric 实施")

    def fetch_post_cut_off_anns(
        self,
        ts_code: str,
        cut_off: date,
        horizon_days: int = 90,
    ) -> list[dict[str, Any]]:
        """Phase 2 M4: 取 cut_off 之后 horizon_days 天的公告."""
        raise NotImplementedError("Phase 2 M4 prediction metric 实施")
