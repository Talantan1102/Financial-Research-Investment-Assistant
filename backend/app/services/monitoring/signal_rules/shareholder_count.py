"""ShareholderCountRule — detects 股东户数骤减(筹码集中预警)."""

from __future__ import annotations

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


class ShareholderCountRule(SignalRule):
    name = "shareholder_count"
    description = "Detects 股东户数骤减 (yellow: -10~-20% / red: < -20%)"

    async def evaluate(
        self,
        customer: MonitoringCustomer,
        tushare: TushareService,
        bocha: BochaService,
        llm: LLMService,
        thresholds: dict[str, float],
    ) -> SignalResult:
        df = await tushare.get_stk_holdernumber(ts_code=customer.ts_code)
        df = df.sort_values("end_date").tail(2)
        if len(df) < 2:
            return SignalResult(
                rule_name=self.name, level=SignalLevel.GREEN, explanation="数据不足"
            )

        prev = float(df["holder_num"].iloc[-2])
        curr = float(df["holder_num"].iloc[-1])
        if prev <= 0:
            return SignalResult(
                rule_name=self.name, level=SignalLevel.GREEN, explanation="数据异常"
            )

        drop_pct = (prev - curr) / prev * 100.0

        if drop_pct >= thresholds["red_drop_pct"]:
            return SignalResult(
                rule_name=self.name,
                level=SignalLevel.RED,
                detected_value=drop_pct,
                threshold=thresholds["red_drop_pct"],
                explanation=f"股东户数环比 -{drop_pct:.1f}% 超 RED 阈值",
                raw_data_ref={"ts_code": customer.ts_code},
            )

        if drop_pct >= thresholds["yellow_min_drop_pct"]:
            return SignalResult(
                rule_name=self.name,
                level=SignalLevel.YELLOW,
                detected_value=drop_pct,
                threshold=thresholds["yellow_min_drop_pct"],
                explanation=f"股东户数环比 -{drop_pct:.1f}% 超 YELLOW 阈值",
                raw_data_ref={"ts_code": customer.ts_code},
            )

        return SignalResult(
            rule_name=self.name, level=SignalLevel.GREEN, explanation="股东户数正常"
        )
