"""PriceAnomalyRule — detects 单日 / 60 日累计跌幅 anomaly."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from app.services.monitoring.signal_rules.base import (
    MonitoringCustomer,
    SignalLevel,
    SignalResult,
    SignalRule,
)

if TYPE_CHECKING:
    from app.services.bocha_factory import BochaService
    from app.services.llm_service import LLMService
    from app.services.tushare_service import TushareService


class PriceAnomalyRule(SignalRule):
    name = "price_anomaly"
    description = "Detects 单日跌幅 / 60 日累计跌幅"

    async def evaluate(
        self,
        customer: MonitoringCustomer,
        tushare: TushareService,
        bocha: BochaService,
        llm: LLMService,
        thresholds: dict[str, float],
    ) -> SignalResult:
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=90)).strftime("%Y%m%d")
        df = await tushare.get_daily(ts_code=customer.ts_code, start=start, end=end)
        df = df.sort_values("trade_date").tail(60)
        if len(df) < 2:
            return SignalResult(
                rule_name=self.name, level=SignalLevel.GREEN, explanation="数据不足"
            )

        prev_close = float(df["close"].iloc[-2])
        curr_close = float(df["close"].iloc[-1])
        single_drop_pct = (prev_close - curr_close) / prev_close * 100.0

        if single_drop_pct >= thresholds["red_single_day_drop_pct"]:
            return SignalResult(
                rule_name=self.name,
                level=SignalLevel.RED,
                detected_value=single_drop_pct,
                threshold=thresholds["red_single_day_drop_pct"],
                explanation=f"单日跌幅 -{single_drop_pct:.1f}% 超 RED 阈值",
                raw_data_ref={"ts_code": customer.ts_code},
            )

        if single_drop_pct >= thresholds["yellow_single_day_drop_pct"]:
            return SignalResult(
                rule_name=self.name,
                level=SignalLevel.YELLOW,
                detected_value=single_drop_pct,
                threshold=thresholds["yellow_single_day_drop_pct"],
                explanation=f"单日跌幅 -{single_drop_pct:.1f}% 超 YELLOW 阈值",
                raw_data_ref={"ts_code": customer.ts_code},
            )

        if len(df) >= 60:
            first = float(df["close"].iloc[0])
            cum_drop_pct = (first - curr_close) / first * 100.0
            if cum_drop_pct >= thresholds["yellow_60d_drop_pct"]:
                return SignalResult(
                    rule_name=self.name,
                    level=SignalLevel.YELLOW,
                    detected_value=cum_drop_pct,
                    threshold=thresholds["yellow_60d_drop_pct"],
                    explanation=f"60 日累计跌幅 -{cum_drop_pct:.1f}% 超阈值",
                    raw_data_ref={"ts_code": customer.ts_code},
                )

        return SignalResult(rule_name=self.name, level=SignalLevel.GREEN, explanation="价格平稳")
