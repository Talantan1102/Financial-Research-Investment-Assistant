"""PortfolioWarningReport — B-3 持仓预警 deliverable schema.

Spec ref: docs/superpowers/specs/2026-05-04-v0.8.3-tushare-and-portfolio-monitoring-design.md § 8
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.services.monitoring.signal_rules.base import SignalLevel, SignalResult


class ReferenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str
    url: str | None = None
    snippet: str = ""


class RiskDiagnosis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    narrative: str
    severity: Literal["low", "medium", "high"]


class DeepDiveSection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str
    evidence_chunk_ids: list[str] = Field(default_factory=list)


class PortfolioWarningReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: str
    customer_name: str
    ts_code: str
    industry: str
    run_id: str
    alert_id: str
    generated_at: datetime
    alert_level: SignalLevel

    summary: str

    triggered_signals: list[SignalResult] = Field(default_factory=list)
    risk_diagnosis: RiskDiagnosis | None = None
    deep_dive: DeepDiveSection | None = None
    recommendations: list[str] = Field(default_factory=list)

    data_sources: list[str] = Field(default_factory=list)
    data_limitations: list[str] = Field(default_factory=list)
    references: list[ReferenceItem] = Field(default_factory=list)
