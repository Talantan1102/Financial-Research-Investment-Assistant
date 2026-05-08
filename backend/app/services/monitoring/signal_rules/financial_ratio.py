"""FinancialRatioRule — detects 资产负债率 jump or 连续亏损."""

from __future__ import annotations

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


class FinancialRatioRule(SignalRule):
    name = "financial_ratio"
    description = "Detects 资产负债率 jump (QoQ +5pp) or 连续 2 季亏损"

    async def evaluate(
        self,
        subject: MonitoringSubject,
        tushare: TushareService,
        bocha: BochaService,
        llm: LLMService,
        thresholds: dict[str, float],
    ) -> SignalResult:
        balance = await tushare.get_balance_sheet(ts_code=subject.ts_code)
        fina = await tushare.get_fina_indicator(ts_code=subject.ts_code)

        balance = balance.sort_values("end_date").tail(4)
        fina = fina.sort_values("end_date").tail(4)

        # Red: debt ratio > 80%
        if not balance.empty:
            latest_debt_pct = float(balance["debt_to_assets"].iloc[-1]) * 100.0
            if latest_debt_pct >= thresholds["red_debt_ratio_abs"]:
                return SignalResult(
                    rule_name=self.name,
                    level=SignalLevel.RED,
                    detected_value=latest_debt_pct,
                    threshold=thresholds["red_debt_ratio_abs"],
                    explanation=f"资产负债率 {latest_debt_pct:.1f}% 超 {thresholds['red_debt_ratio_abs']}%",
                    raw_data_ref={
                        "ts_code": subject.ts_code,
                        "end_date": str(balance["end_date"].iloc[-1]),
                    },
                )

        # Red: 连续 2 季净利率为负
        if len(fina) >= 2:
            last_two_margins = fina["netprofit_margin"].tail(2).tolist()
            if all(m < 0 for m in last_two_margins):
                return SignalResult(
                    rule_name=self.name,
                    level=SignalLevel.RED,
                    detected_value=str(last_two_margins),
                    threshold="0",
                    explanation=f"连续 2 季净利率为负: {last_two_margins}",
                    raw_data_ref={"ts_code": subject.ts_code},
                )

        # Yellow: debt ratio QoQ jump >= +5pp
        if len(balance) >= 2:
            qoq_delta_pp = (
                float(balance["debt_to_assets"].iloc[-1])
                - float(balance["debt_to_assets"].iloc[-2])
            ) * 100.0
            if qoq_delta_pp >= thresholds["yellow_debt_ratio_qoq_pp"]:
                return SignalResult(
                    rule_name=self.name,
                    level=SignalLevel.YELLOW,
                    detected_value=qoq_delta_pp,
                    threshold=thresholds["yellow_debt_ratio_qoq_pp"],
                    explanation=f"资产负债率单季环比 +{qoq_delta_pp:.1f}pp 超阈值",
                    raw_data_ref={"ts_code": subject.ts_code},
                )

        # Yellow: 净利率为负
        if not fina.empty:
            latest_margin = float(fina["netprofit_margin"].iloc[-1])
            if latest_margin < thresholds["yellow_net_margin_negative"]:
                return SignalResult(
                    rule_name=self.name,
                    level=SignalLevel.YELLOW,
                    detected_value=latest_margin,
                    threshold=0.0,
                    explanation=f"最新净利率 {latest_margin:.2%} 为负",
                    raw_data_ref={"ts_code": subject.ts_code},
                )

        return SignalResult(
            rule_name=self.name,
            level=SignalLevel.GREEN,
            detected_value=None,
            threshold=None,
            explanation="财务比率正常",
            raw_data_ref=None,
        )
