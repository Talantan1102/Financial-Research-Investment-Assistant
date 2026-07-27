"""Durable PostgreSQL facts for paper-account market suitability and permissions."""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base
from app.models.paper_account import PaperAccount


class Market(enum.StrEnum):
    MAIN = "main"
    CHINEXT = "chinext"
    STAR = "star"
    BSE = "bse"


class EntitlementStatus(enum.StrEnum):
    NOT_APPLIED = "not_applied"
    PENDING_DISCLOSURE = "pending_disclosure"
    ENABLED = "enabled"
    RESTRICTED = "restricted"
    REVOKED = "revoked"


class ApplicationStatus(enum.StrEnum):
    IN_PROGRESS = "in_progress"
    AWAITING_INFORMATION = "awaiting_information"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    CANCELLED_BY_USER = "cancelled_by_user"
    EXPIRED = "expired"
    REJECTED = "rejected"
    COMPLETED = "completed"


class AssessmentDecision(enum.StrEnum):
    PASSED = "passed"
    REJECTED = "rejected"


_MARKET = Enum(Market, name="market_access_market", values_callable=lambda members: [m.value for m in members], validate_strings=True)
_ENTITLEMENT_STATUS = Enum(EntitlementStatus, name="market_entitlement_status", values_callable=lambda members: [m.value for m in members], validate_strings=True)
_APPLICATION_STATUS = Enum(ApplicationStatus, name="entitlement_application_status", values_callable=lambda members: [m.value for m in members], validate_strings=True)
_ASSESSMENT_DECISION = Enum(AssessmentDecision, name="suitability_assessment_decision", values_callable=lambda members: [m.value for m in members], validate_strings=True)


class InvestorSuitabilityProfile(Base):
    __tablename__ = "investor_suitability_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    investor_type = Column(String(32), nullable=False)
    risk_level = Column(String(16), nullable=False)
    securities_experience_months = Column(Integer, nullable=False)
    declared_average_assets_20d = Column(Numeric(18, 2), nullable=False)
    assessed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("securities_experience_months >= 0", name="ck_investor_suitability_profiles_experience_nonnegative"),
        CheckConstraint("declared_average_assets_20d >= 0 AND declared_average_assets_20d::text NOT IN ('NaN', 'Infinity', '-Infinity')", name="ck_investor_suitability_profiles_assets_valid"),
    )


class MarketAccessRule(Base):
    __tablename__ = "market_access_rules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    market = Column(_MARKET, nullable=False)
    effective_from = Column(Date, nullable=False)
    minimum_average_assets_20d = Column(Numeric(18, 2), nullable=True)
    minimum_experience_months = Column(Integer, nullable=True)
    required_disclosure_version = Column(String(64), nullable=False)
    rule_version = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("market", "rule_version", name="uq_market_access_rules_market_version"),
        UniqueConstraint("market", "effective_from", name="uq_market_access_rules_market_effective_from"),
        CheckConstraint("minimum_average_assets_20d IS NULL OR (minimum_average_assets_20d >= 0 AND minimum_average_assets_20d::text NOT IN ('NaN', 'Infinity', '-Infinity'))", name="ck_market_access_rules_assets_valid"),
        CheckConstraint("minimum_experience_months IS NULL OR minimum_experience_months >= 0", name="ck_market_access_rules_experience_nonnegative"),
    )


class SuitabilityAssessment(Base):
    __tablename__ = "suitability_assessments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    account_generation = Column(Integer, nullable=False)
    market = Column(_MARKET, nullable=False)
    submitted_snapshot = Column(JSONB(none_as_null=True), nullable=False)
    decision = Column(_ASSESSMENT_DECISION, nullable=False)
    failed_conditions = Column(JSONB(none_as_null=True), nullable=True)
    rule_version = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        ForeignKeyConstraint(["account_id", "account_generation"], ["paper_accounts.id", "paper_accounts.generation"], name="fk_suitability_assessments_account_generation", ondelete="RESTRICT"),
        ForeignKeyConstraint(
            ["market", "rule_version"],
            ["market_access_rules.market", "market_access_rules.rule_version"],
            name="fk_suitability_assessments_market_access_rule",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "account_id", "account_generation", "market", name="uq_suitability_assessments_fact_owner"),
        CheckConstraint("account_generation > 0", name="ck_suitability_assessments_generation_positive"),
        CheckConstraint(
            "jsonb_typeof(submitted_snapshot) = 'object'",
            name="ck_suitability_assessments_snapshot_object",
        ),
        CheckConstraint(
            "(decision = 'passed' AND failed_conditions IS NULL) OR "
            "(decision = 'rejected' AND jsonb_typeof(failed_conditions) = 'array' "
            "AND jsonb_array_length(failed_conditions) > 0)",
            name="ck_suitability_assessments_decision_failures",
        ),
    )


class RiskDisclosureAcceptance(Base):
    __tablename__ = "risk_disclosure_acceptances"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    account_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    account_generation = Column(Integer, nullable=False)
    market = Column(_MARKET, nullable=False)
    disclosure_version = Column(String(64), nullable=False)
    accepted_at = Column(DateTime(timezone=True), nullable=False)
    source = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        ForeignKeyConstraint(["account_id", "account_generation"], ["paper_accounts.id", "paper_accounts.generation"], name="fk_risk_disclosure_acceptances_account_generation", ondelete="RESTRICT"),
        ForeignKeyConstraint(
            ["application_id", "account_id", "account_generation", "market"],
            [
                "entitlement_applications.id",
                "entitlement_applications.account_id",
                "entitlement_applications.account_generation",
                "entitlement_applications.market",
            ],
            name="fk_risk_disclosure_acceptances_application_owner",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "application_id",
            "disclosure_version",
            name="uq_risk_disclosure_acceptances_application_version",
        ),
        CheckConstraint("account_generation > 0", name="ck_risk_disclosure_acceptances_generation_positive"),
        CheckConstraint("btrim(source) <> ''", name="ck_risk_disclosure_acceptances_source_nonblank"),
    )


class MarketEntitlement(Base):
    __tablename__ = "market_entitlements"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    account_generation = Column(Integer, nullable=False)
    market = Column(_MARKET, nullable=False)
    status = Column(_ENTITLEMENT_STATUS, nullable=False)
    can_buy = Column(Boolean, nullable=False, default=False)
    can_sell = Column(Boolean, nullable=False, default=False)
    can_subscribe = Column(Boolean, nullable=False, default=False)
    # A newly-created, not-applied entitlement has not yet been assessed
    # against a market rule. Every later state records the rule it relies on.
    rule_version = Column(String(64), nullable=True)
    enabled_at = Column(DateTime(timezone=True), nullable=True)
    restricted_at = Column(DateTime(timezone=True), nullable=True)
    reason_code = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        ForeignKeyConstraint(["account_id", "account_generation"], ["paper_accounts.id", "paper_accounts.generation"], name="fk_market_entitlements_account_generation", ondelete="RESTRICT"),
        ForeignKeyConstraint(
            ["market", "rule_version"],
            ["market_access_rules.market", "market_access_rules.rule_version"],
            name="fk_market_entitlements_market_access_rule",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("account_id", "account_generation", "market", name="uq_market_entitlements_account_generation_market"),
        UniqueConstraint("id", "account_id", "account_generation", "market", name="uq_market_entitlements_fact_owner"),
        CheckConstraint("account_generation > 0", name="ck_market_entitlements_generation_positive"),
        CheckConstraint(
            "("
            "(status = 'enabled' AND (can_buy OR can_sell OR can_subscribe) "
            "AND enabled_at IS NOT NULL AND restricted_at IS NULL AND rule_version IS NOT NULL) "
            "OR "
            "(status = 'not_applied' "
            "AND NOT can_buy AND NOT can_sell AND NOT can_subscribe "
            "AND enabled_at IS NULL AND restricted_at IS NULL AND rule_version IS NULL) "
            "OR "
            "(status IN ('pending_disclosure', 'revoked') "
            "AND NOT can_buy AND NOT can_sell AND NOT can_subscribe "
            "AND enabled_at IS NULL AND restricted_at IS NULL AND rule_version IS NOT NULL) "
            "OR "
            "(status = 'restricted' AND NOT can_buy AND NOT can_subscribe "
            "AND enabled_at IS NOT NULL AND restricted_at IS NOT NULL AND rule_version IS NOT NULL)"
            ")",
            name="ck_market_entitlements_status_capabilities_timestamps",
        ),
    )

    @classmethod
    def new(cls, *, account: PaperAccount, market: Market) -> MarketEntitlement:
        return cls(account_id=account.id, account_generation=account.generation, market=market, status=EntitlementStatus.NOT_APPLIED, can_buy=False, can_sell=False, can_subscribe=False, rule_version=None)


class EntitlementApplication(Base):
    __tablename__ = "entitlement_applications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    account_generation = Column(Integer, nullable=False)
    market = Column(_MARKET, nullable=False)
    status = Column(_APPLICATION_STATUS, nullable=False)
    assessment_id = Column(UUID(as_uuid=True), nullable=True, unique=True)
    enabled_entitlement_id = Column(UUID(as_uuid=True), nullable=True, unique=True)
    start_idempotency_key = Column(String(128), nullable=False)
    confirm_idempotency_key = Column(String(128), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
    cancel_reason = Column(String(256), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        ForeignKeyConstraint(
            ["account_id", "user_id", "account_generation"],
            ["paper_accounts.id", "paper_accounts.user_id", "paper_accounts.generation"],
            name="fk_entitlement_applications_account_user_generation",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["assessment_id", "account_id", "account_generation", "market"],
            ["suitability_assessments.id", "suitability_assessments.account_id", "suitability_assessments.account_generation", "suitability_assessments.market"],
            name="fk_entitlement_applications_assessment_owner",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "id", "account_id", "account_generation", "market",
            name="uq_entitlement_applications_fact_owner",
        ),
        UniqueConstraint(
            "user_id", "start_idempotency_key",
            name="uq_entitlement_applications_user_start_idempotency_key",
        ),
        UniqueConstraint(
            "user_id", "confirm_idempotency_key",
            name="uq_entitlement_applications_user_confirm_idempotency_key",
        ),
        ForeignKeyConstraint(
            ["enabled_entitlement_id", "account_id", "account_generation", "market"],
            ["market_entitlements.id", "market_entitlements.account_id", "market_entitlements.account_generation", "market_entitlements.market"],
            name="fk_entitlement_applications_enabled_entitlement_owner",
            ondelete="RESTRICT",
        ),
        CheckConstraint("account_generation > 0", name="ck_entitlement_applications_generation_positive"),
        CheckConstraint("btrim(start_idempotency_key) <> ''", name="ck_entitlement_applications_start_idempotency_key_nonblank"),
        CheckConstraint("confirm_idempotency_key IS NULL OR btrim(confirm_idempotency_key) <> ''", name="ck_entitlement_applications_confirm_idempotency_key_nonblank"),
        CheckConstraint(
            "("
            "(status = 'completed' AND completed_at IS NOT NULL AND enabled_entitlement_id IS NOT NULL) "
            "OR "
            "(status IN ('cancelled_by_user', 'expired', 'rejected') "
            "AND completed_at IS NOT NULL AND enabled_entitlement_id IS NULL) "
            "OR "
            "(status IN ('in_progress', 'awaiting_information', 'awaiting_confirmation') "
            "AND completed_at IS NULL AND enabled_entitlement_id IS NULL)"
            ")",
            name="ck_entitlement_applications_status_completion",
        ),
    )

    # A PostgreSQL CHECK cannot inspect the referenced entitlement's status.
    # The composite FK guarantees ownership; Task 3's atomic confirm service must
    # additionally require that enabled_entitlement.status is ENABLED.

    @classmethod
    def new(
        cls, *, account: PaperAccount, market: Market, start_idempotency_key: str
    ) -> EntitlementApplication:
        return cls(
            account_id=account.id,
            user_id=account.user_id,
            account_generation=account.generation,
            market=market,
            status=ApplicationStatus.IN_PROGRESS,
            start_idempotency_key=start_idempotency_key,
        )
