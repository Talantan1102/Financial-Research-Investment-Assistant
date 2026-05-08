"""PriceAnomalyRule — 对称化 ±5%/±10% 涨跌(spec § 4.4 + decision via § 5.1)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from app.services.monitoring.signal_rules.base import (
    MonitoringSubject,
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
    description = "Detects |涨跌| ≥5/10% 单日 / 60 日累计 ±20%"

    async def evaluate(
        self,
        subject: MonitoringSubject,
        tushare: TushareService,
        bocha: BochaService,
        llm: LLMService,
        thresholds: dict[str, float],
    ) -> SignalResult:
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=90)).strftime("%Y%m%d")
        df = await tushare.get_daily(ts_code=subject.ts_code, start=start, end=end)
        df = df.sort_values("trade_date").tail(60)
        if len(df) < 2:
            return SignalResult(
                rule_name=self.name, level=SignalLevel.GREEN, explanation="数据不足"
            )

        prev_close = float(df["close"].iloc[-2])
        curr_close = float(df["close"].iloc[-1])
        single_change_pct = (curr_close - prev_close) / prev_close * 100.0  # 正涨负跌
        single_abs_pct = abs(single_change_pct)

        red_th = thresholds.get("red_single_day_change_pct", 10.0)
        yellow_th = thresholds.get("yellow_single_day_change_pct", 5.0)

        if single_abs_pct >= red_th:
            return SignalResult(
                rule_name=self.name,
                level=SignalLevel.RED,
                detected_value=single_change_pct,
                threshold=red_th,
                explanation=f"单日 {single_change_pct:+.1f}% 超 RED ±{red_th}% 阈值",
                raw_data_ref={"ts_code": subject.ts_code},
            )

        if single_abs_pct >= yellow_th:
            return SignalResult(
                rule_name=self.name,
                level=SignalLevel.YELLOW,
                detected_value=single_change_pct,
                threshold=yellow_th,
                explanation=f"单日 {single_change_pct:+.1f}% 超 YELLOW ±{yellow_th}% 阈值",
                raw_data_ref={"ts_code": subject.ts_code},
            )

        if len(df) >= 60:
            first = float(df["close"].iloc[0])
            cum_change_pct = (curr_close - first) / first * 100.0
            cum_60d_th = thresholds.get("yellow_60d_change_pct", 20.0)
            if abs(cum_change_pct) >= cum_60d_th:
                return SignalResult(
                    rule_name=self.name,
                    level=SignalLevel.YELLOW,
                    detected_value=cum_change_pct,
                    threshold=cum_60d_th,
                    explanation=f"60 日累计 {cum_change_pct:+.1f}% 超 ±{cum_60d_th}% 阈值",
                    raw_data_ref={"ts_code": subject.ts_code},
                )

        return SignalResult(rule_name=self.name, level=SignalLevel.GREEN, explanation="价格平稳")
