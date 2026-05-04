"""CashFlowRule — detects 经营性现金流恶化 or 连续负值."""

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


class CashFlowRule(SignalRule):
    name = "cash_flow"
    description = "Detects 经营性现金流单季环比下滑 / 连续 2 季负值"

    async def evaluate(
        self,
        customer: MonitoringCustomer,
        tushare: TushareService,
        bocha: BochaService,
        llm: LLMService,
        thresholds: dict[str, float],
    ) -> SignalResult:
        df = await tushare.get_cashflow(ts_code=customer.ts_code)
        df = df.sort_values("end_date").tail(4)

        if len(df) >= 2:
            last_two = df["n_cashflow_act"].tail(2).tolist()
            if all(v < 0 for v in last_two):
                return SignalResult(
                    rule_name=self.name,
                    level=SignalLevel.RED,
                    detected_value=str(last_two),
                    threshold="0",
                    explanation=f"经营性现金流连续 2 季为负: {last_two}",
                    raw_data_ref={"ts_code": customer.ts_code},
                )

            prev = float(df["n_cashflow_act"].iloc[-2])
            curr = float(df["n_cashflow_act"].iloc[-1])
            if prev > 0:
                drop_pct = (prev - curr) / prev * 100.0
                if drop_pct >= thresholds["yellow_op_cf_qoq_drop_pct"]:
                    return SignalResult(
                        rule_name=self.name,
                        level=SignalLevel.YELLOW,
                        detected_value=drop_pct,
                        threshold=thresholds["yellow_op_cf_qoq_drop_pct"],
                        explanation=f"经营性现金流单季环比 -{drop_pct:.1f}% 超阈值",
                        raw_data_ref={"ts_code": customer.ts_code},
                    )

        return SignalResult(
            rule_name=self.name,
            level=SignalLevel.GREEN,
            explanation="现金流正常",
        )
