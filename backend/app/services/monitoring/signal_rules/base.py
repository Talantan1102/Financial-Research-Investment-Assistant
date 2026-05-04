"""SignalRule ABC + Level enum + Result schema."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict

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


class MonitoringCustomer(BaseModel):
    """Subset of monitoring_customers row used by signal rules."""

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
        customer: MonitoringCustomer,
        tushare: TushareService,
        bocha: BochaService,
        llm: LLMService,
        thresholds: dict[str, float],
    ) -> SignalResult: ...
