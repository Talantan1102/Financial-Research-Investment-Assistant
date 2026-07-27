"""HTTP schemas for the traditional market-permission application flow."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.investor_suitability import (
    ApplicationStatus,
    AssessmentDecision,
    EntitlementStatus,
    Market,
)


class StartApplicationRequest(BaseModel):
    """Start one market-permission application for the current paper account."""

    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(
        min_length=1,
        max_length=128,
        description="本次发起申请的客户端幂等键；同一用户重复提交会返回同一申请。",
    )


class SubmitProfileRequest(BaseModel):
    """User-entered facts used only by the deterministic suitability check."""

    model_config = ConfigDict(extra="forbid")

    declared_average_assets_20d: Decimal = Field(
        ge=0,
        max_digits=18,
        decimal_places=2,
        description="用户申报的最近二十个交易日日均证券资产，单位为人民币元。",
    )
    securities_experience_months: int = Field(ge=0, description="用户申报的证券交易经验月数。")
    risk_level: str = Field(
        min_length=1, max_length=16, description="用户当前风险等级，例如 C4；用于留存申请资料快照。"
    )


class ConfirmApplicationRequest(BaseModel):
    """Confirm the currently required risk disclosure and enable the permission."""

    model_config = ConfigDict(extra="forbid")

    disclosure_version: str = Field(
        min_length=1,
        max_length=64,
        description="用户本次确认签署的风险揭示书版本，必须是当前市场要求的版本。",
    )
    idempotency_key: str = Field(
        min_length=1,
        max_length=128,
        description="本次确认开通的客户端幂等键；重复提交不会重复开通权限。",
    )


class ApplicationRead(BaseModel):
    """A user-owned permission application and its current state."""

    model_config = ConfigDict(from_attributes=True)

    application_id: UUID = Field(validation_alias="id", description="权限申请的唯一编号。")
    market: Market = Field(description="申请开通的交易市场。")
    status: ApplicationStatus = Field(description="申请当前状态，例如待补资料、待确认或已完成。")
    assessment_id: UUID | None = Field(
        description="本次申请最近一次适当性评估的唯一编号；尚未提交资料时为空。"
    )
    started_at: datetime = Field(description="用户发起本次申请的时间。")
    completed_at: datetime | None = Field(
        description="申请完成、取消、拒绝或过期的时间；未结束时为空。"
    )


class AssessmentRead(BaseModel):
    """The deterministic result returned after profile submission."""

    model_config = ConfigDict(from_attributes=True)

    assessment_id: UUID = Field(validation_alias="id", description="适当性评估的唯一编号。")
    market: Market = Field(description="本次评估对应的交易市场。")
    decision: AssessmentDecision = Field(description="评估结论：通过或不通过。")
    failed_conditions: list[dict[str, object]] | None = Field(
        description="未满足的准入条件；通过时为空。"
    )
    rule_version: str = Field(description="本次评估采用的市场准入规则版本。")


class MarketEntitlementRead(BaseModel):
    """The durable permission facts used later by order eligibility checks."""

    model_config = ConfigDict(from_attributes=True)

    entitlement_id: UUID = Field(validation_alias="id", description="市场权限记录的唯一编号。")
    market: Market = Field(description="权限对应的交易市场。")
    status: EntitlementStatus = Field(description="权限状态，例如已开通、受限或未申请。")
    can_buy: bool = Field(description="用户是否可以在该市场买入证券。")
    can_sell: bool = Field(description="用户是否可以在该市场卖出已有持仓。")
    can_subscribe: bool = Field(description="用户是否可以参与该市场的新股申购。")
    rule_version: str | None = Field(description="权限所依据的准入规则版本；未申请时为空。")
    enabled_at: datetime | None = Field(description="权限开通时间；未开通时为空。")
    restricted_at: datetime | None = Field(description="权限受限时间；未受限时为空。")
