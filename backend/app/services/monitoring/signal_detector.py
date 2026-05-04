"""SignalDetector — runs all SignalRules concurrently, aggregates max level."""

from __future__ import annotations

import asyncio
import logging
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

_logger = logging.getLogger(__name__)


_LEVEL_ORDER = {SignalLevel.GREEN: 0, SignalLevel.YELLOW: 1, SignalLevel.RED: 2}


class SignalDetector:
    def __init__(self, rules: list[SignalRule]) -> None:
        if not rules:
            raise ValueError("rules must not be empty")
        self._rules = rules

    async def detect(
        self,
        customer: MonitoringCustomer,
        tushare: TushareService,
        bocha: BochaService,
        llm: LLMService,
        thresholds_per_rule: dict[str, dict[str, float]],
    ) -> tuple[SignalLevel, list[SignalResult]]:
        async def _safe(rule: SignalRule) -> SignalResult:
            try:
                rule_thresh = thresholds_per_rule.get(rule.name, {})
                return await rule.evaluate(customer, tushare, bocha, llm, rule_thresh)
            except Exception as exc:
                _logger.warning("signal rule %s failed: %s", rule.name, exc)
                return SignalResult(
                    rule_name=rule.name,
                    level=SignalLevel.GREEN,
                    explanation=f"error: {exc}",
                )

        results = await asyncio.gather(*(_safe(r) for r in self._rules))
        overall = max(results, key=lambda r: _LEVEL_ORDER[r.level]).level
        return overall, list(results)
