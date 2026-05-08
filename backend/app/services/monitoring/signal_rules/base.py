"""SignalRule ABC + Level enum + Result schema."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict

from app.services.monitoring.scope import MonitoringSubject

if TYPE_CHECKING:
    from app.services.bocha_factory import BochaService
    from app.services.llm_service import LLMService
    from app.services.tushare_service import TushareService


class SignalLevel(StrEnum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


class SignalResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_name: str
    level: SignalLevel
    detected_value: float | str | None = None
    threshold: float | str | None = None
    explanation: str
    raw_data_ref: dict[str, Any] | None = None


# Backward-compat schema — to be removed in Task 14 when monitoring_service.py 退役.
# v1.0 spec § 1 决策 2 把 scope 从 monitoring_customers 切到 positions,新代码统一用
# `MonitoringSubject` (scope.py)。escalation.py + monitoring_service.py 仍按旧
# schema(id / industry / thresholds_override)实例化此类,Task 14 同步删除。
class MonitoringCustomer(BaseModel):
    """Legacy v0.8.3 schema(monitoring_customers row)— 仅遗留代码使用。"""

    model_config = ConfigDict(extra="forbid")

    id: str
    ts_code: str
    name: str
    industry: str
    thresholds_override: dict[str, float] | None = None


class SignalRule(ABC):
    name: str = ""
    description: str = ""

    @abstractmethod
    async def evaluate(
        self,
        subject: MonitoringSubject,
        tushare: TushareService,
        bocha: BochaService,
        llm: LLMService,
        thresholds: dict[str, float],
    ) -> SignalResult: ...


__all__ = [
    "MonitoringCustomer",
    "MonitoringSubject",
    "SignalLevel",
    "SignalResult",
    "SignalRule",
]
