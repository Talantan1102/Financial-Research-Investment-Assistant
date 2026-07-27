"""Transactional workflow for user-operated market-permission applications."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select, text, tuple_
from sqlalchemy.orm import Session

from app.models.investor_suitability import (
    ApplicationStatus,
    EntitlementApplication,
    EntitlementStatus,
    InvestorSuitabilityProfile,
    Market,
    MarketEntitlement,
    RiskDisclosureAcceptance,
    SuitabilityAssessment,
)
from app.models.investor_suitability import (
    AssessmentDecision as AssessmentDecisionStatus,
)
from app.models.investor_suitability import (
    MarketAccessRule as PersistedMarketAccessRule,
)
from app.models.paper_account import PaperAccount, PaperAccountStatus
from app.services.investor_suitability.rules import (
    MarketAccessRule,
    MarketRuleBook,
    evaluate_market_access,
    rulebook,
)


class SuitabilityApplicationError(RuntimeError):
    """Stable service error for the traditional permission-application flow."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class SuitabilityApplicationService:
    """State machine whose caller owns the surrounding database transaction."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def start(
        self,
        *,
        user_id: uuid.UUID,
        account_id: uuid.UUID,
        market: Market,
        idempotency_key: str,
    ) -> EntitlementApplication:
        key = _require_key(idempotency_key)
        self._lock_key("start", user_id, key)
        replay = self._session.scalar(
            select(EntitlementApplication).where(
                EntitlementApplication.user_id == user_id,
                EntitlementApplication.start_idempotency_key == key,
            )
        )
        if replay is not None:
            if replay.account_id != account_id or replay.market is not market:
                raise SuitabilityApplicationError("idempotency_conflict", "申请请求键与原请求不一致")
            return replay

        account = self._active_account(user_id=user_id, account_id=account_id, for_update=True)
        enabled = self._session.scalar(
            select(MarketEntitlement).where(
                MarketEntitlement.account_id == account.id,
                MarketEntitlement.account_generation == account.generation,
                MarketEntitlement.market == market,
                MarketEntitlement.status == EntitlementStatus.ENABLED,
            )
        )
        if enabled is not None:
            raise SuitabilityApplicationError(
                "market_already_enabled", "该市场权限已经开通，无需重复申请"
            )
        application = EntitlementApplication.new(
            account=account, market=market, start_idempotency_key=key
        )
        self._session.add(application)
        self._session.flush()
        return application

    def submit_profile(
        self,
        *,
        user_id: uuid.UUID,
        application_id: uuid.UUID,
        average_assets_20d: Decimal,
        experience_months: int,
        risk_level: str,
    ) -> SuitabilityAssessment:
        application = self._application(user_id=user_id, application_id=application_id, for_update=True)
        self._require_open(application)
        self._active_account(
            user_id=user_id,
            account_id=application.account_id,
            generation=application.account_generation,
            for_update=True,
        )
        assets = _nonnegative_decimal(average_assets_20d, "average_assets_20d")
        months = _nonnegative_int(experience_months, "experience_months")
        level = _require_text(risk_level, "risk_level", 16)
        rules = self._locked_current_rules()
        result = evaluate_market_access(rules, application.market, assets, months)

        profile = self._session.scalar(
            select(InvestorSuitabilityProfile)
            .where(InvestorSuitabilityProfile.user_id == user_id)
            .order_by(InvestorSuitabilityProfile.created_at.desc())
            .with_for_update()
        )
        if profile is None:
            profile = InvestorSuitabilityProfile(
                user_id=user_id,
                investor_type="ordinary_individual",
                risk_level=level,
                declared_average_assets_20d=assets,
                securities_experience_months=months,
                assessed_at=datetime.now(UTC),
            )
            self._session.add(profile)
        else:
            profile.risk_level = level
            profile.declared_average_assets_20d = assets
            profile.securities_experience_months = months
            profile.assessed_at = datetime.now(UTC)

        assessment = SuitabilityAssessment(
            account_id=application.account_id,
            account_generation=application.account_generation,
            market=application.market,
            submitted_snapshot={
                "average_assets_20d": str(assets),
                "experience_months": months,
                "risk_level": level,
            },
            decision=(AssessmentDecisionStatus.PASSED if result.allowed else AssessmentDecisionStatus.REJECTED),
            failed_conditions=(None if result.allowed else [item.model_dump(mode="json") for item in result.failed_conditions]),
            rule_version=result.rule_version,
        )
        self._session.add(assessment)
        self._session.flush()
        application.assessment_id = assessment.id
        application.status = (
            ApplicationStatus.AWAITING_CONFIRMATION
            if result.allowed
            else ApplicationStatus.AWAITING_INFORMATION
        )
        self._session.flush()
        return assessment

    def confirm(
        self,
        *,
        user_id: uuid.UUID,
        application_id: uuid.UUID,
        disclosure_version: str,
        idempotency_key: str,
    ) -> MarketEntitlement:
        key = _require_key(idempotency_key)
        disclosure = _require_text(disclosure_version, "disclosure_version", 64)
        self._lock_key("confirm", user_id, key)
        keyed = self._session.scalar(
            select(EntitlementApplication).where(
                EntitlementApplication.user_id == user_id,
                EntitlementApplication.confirm_idempotency_key == key,
            )
        )
        if keyed is not None and keyed.id != application_id:
            raise SuitabilityApplicationError("idempotency_conflict", "确认请求键与原请求不一致")

        application = self._application(user_id=user_id, application_id=application_id, for_update=True)
        if application.confirm_idempotency_key is not None:
            if application.confirm_idempotency_key != key:
                raise SuitabilityApplicationError("confirmation_conflict", "申请已使用其他确认请求键")
            acceptance = self.disclosure_for(application.id)
            if acceptance is None:
                raise SuitabilityApplicationError(
                    "invalid_confirmed_application", "已确认申请缺少风险揭示书记录"
                )
            if acceptance.disclosure_version != disclosure:
                raise SuitabilityApplicationError(
                    "idempotency_conflict", "确认请求键与首次提交的风险揭示书版本不一致"
                )
            if application.status is ApplicationStatus.COMPLETED:
                entitlement = self._session.get(MarketEntitlement, application.enabled_entitlement_id)
                if entitlement is None or entitlement.status is not EntitlementStatus.ENABLED:
                    raise SuitabilityApplicationError("invalid_completed_application", "已完成申请缺少有效权限")
                return entitlement
            if application.status is ApplicationStatus.REJECTED:
                raise SuitabilityApplicationError("application_not_eligible", "当前资料不满足开通条件")
        elif keyed is not None:
            raise SuitabilityApplicationError("idempotency_conflict", "确认请求键与原请求不一致")

        self._require_open(application)
        account = self._active_account(
            user_id=user_id,
            account_id=application.account_id,
            generation=application.account_generation,
            for_update=True,
        )
        self._lock_market(application.account_id, application.account_generation, application.market)
        rules = self._locked_current_rules()
        current_rule = rules.current(application.market)
        if disclosure != current_rule.required_disclosure_version:
            raise SuitabilityApplicationError("stale_disclosure_version", "风险揭示书版本已过期，请重新查看")
        assessment = self._session.get(SuitabilityAssessment, application.assessment_id)
        if assessment is None:
            raise SuitabilityApplicationError("profile_required", "请先提交适当性资料")
        snapshot = assessment.submitted_snapshot
        result = evaluate_market_access(
            rules,
            application.market,
            Decimal(str(snapshot["average_assets_20d"])),
            int(snapshot["experience_months"]),
        )
        if not result.allowed:
            now = datetime.now(UTC)
            self._session.add(
                RiskDisclosureAcceptance(
                    application_id=application.id,
                    account_id=account.id,
                    account_generation=account.generation,
                    market=application.market,
                    disclosure_version=disclosure,
                    accepted_at=now,
                    source="suitability_application",
                )
            )
            application.confirm_idempotency_key = key
            application.status = ApplicationStatus.REJECTED
            application.completed_at = now
            self._session.flush()
            raise SuitabilityApplicationError("application_not_eligible", "当前资料不满足开通条件")

        entitlement = self._session.scalar(
            select(MarketEntitlement)
            .where(
                MarketEntitlement.account_id == account.id,
                MarketEntitlement.account_generation == account.generation,
                MarketEntitlement.market == application.market,
            )
            .with_for_update()
        )
        if entitlement is not None:
            raise SuitabilityApplicationError("market_already_enabled", "该市场权限已存在，请刷新后查看")

        now = datetime.now(UTC)
        entitlement = MarketEntitlement(
            account_id=account.id,
            account_generation=account.generation,
            market=application.market,
            status=EntitlementStatus.ENABLED,
            can_buy=True,
            can_sell=True,
            can_subscribe=True,
            rule_version=current_rule.rule_version,
            enabled_at=now,
        )
        self._session.add(entitlement)
        self._session.flush()
        self._session.add(
            RiskDisclosureAcceptance(
                application_id=application.id,
                account_id=account.id,
                account_generation=account.generation,
                market=application.market,
                disclosure_version=disclosure,
                accepted_at=now,
                source="suitability_application",
            )
        )
        application.confirm_idempotency_key = key
        application.enabled_entitlement_id = entitlement.id
        application.status = ApplicationStatus.COMPLETED
        application.completed_at = now
        self._session.flush()
        return entitlement

    def cancel(self, *, user_id: uuid.UUID, application_id: uuid.UUID) -> EntitlementApplication:
        application = self._application(user_id=user_id, application_id=application_id, for_update=True)
        self._require_open(application)
        application.status = ApplicationStatus.CANCELLED_BY_USER
        application.completed_at = datetime.now(UTC)
        self._session.flush()
        return application

    def list_entitlements(
        self, *, user_id: uuid.UUID, account_id: uuid.UUID
    ) -> list[MarketEntitlement]:
        account = self._active_account(user_id=user_id, account_id=account_id)
        return list(
            self._session.scalars(
                select(MarketEntitlement)
                .where(
                    MarketEntitlement.account_id == account.id,
                    MarketEntitlement.account_generation == account.generation,
                )
                .order_by(MarketEntitlement.market)
            )
        )

    def disclosure_for(self, application_id: uuid.UUID) -> RiskDisclosureAcceptance | None:
        return self._session.scalar(
            select(RiskDisclosureAcceptance).where(
                RiskDisclosureAcceptance.application_id == application_id
            )
        )

    def entitlement_for(self, account_id: uuid.UUID, market: Market) -> MarketEntitlement | None:
        return self._session.scalar(
            select(MarketEntitlement).where(
                MarketEntitlement.account_id == account_id,
                MarketEntitlement.market == market,
            )
        )

    def _application(self, *, user_id: uuid.UUID, application_id: uuid.UUID, for_update: bool) -> EntitlementApplication:
        statement = select(EntitlementApplication).where(
            EntitlementApplication.id == application_id,
            EntitlementApplication.user_id == user_id,
        )
        if for_update:
            statement = statement.with_for_update()
        application = self._session.scalar(statement)
        if application is None:
            raise SuitabilityApplicationError("application_not_found", "权限申请不存在")
        return application

    def _active_account(self, *, user_id: uuid.UUID, account_id: uuid.UUID, generation: int | None = None, for_update: bool = False) -> PaperAccount:
        statement = select(PaperAccount).where(
            PaperAccount.id == account_id,
            PaperAccount.user_id == user_id,
            PaperAccount.status == PaperAccountStatus.ACTIVE,
        )
        if generation is not None:
            statement = statement.where(PaperAccount.generation == generation)
        if for_update:
            statement = statement.with_for_update()
        account = self._session.scalar(statement)
        if account is None:
            raise SuitabilityApplicationError("stale_account_generation", "账户已重置，请重新发起申请")
        return account

    def _locked_current_rules(self) -> MarketRuleBook:
        configured = rulebook()
        rows = self._session.scalars(
            select(PersistedMarketAccessRule)
            .where(
                tuple_(PersistedMarketAccessRule.market, PersistedMarketAccessRule.rule_version).in_(
                    [(item.market, item.rule_version) for item in configured.rules]
                )
            )
            .with_for_update()
        ).all()
        if len(rows) != len(configured.rules):
            raise SuitabilityApplicationError("market_rules_unavailable", "市场准入规则暂不可用")
        by_market = {row.market: row for row in rows}
        return MarketRuleBook(
            rulebook_version=configured.rulebook_version,
            rules=tuple(
                MarketAccessRule(
                    market=item.market,
                    rule_version=by_market[item.market].rule_version,
                    minimum_average_assets_20d=by_market[item.market].minimum_average_assets_20d,
                    minimum_experience_months=by_market[item.market].minimum_experience_months,
                    required_disclosure_version=by_market[item.market].required_disclosure_version,
                )
                for item in configured.rules
            ),
        )

    def _lock_key(self, kind: str, user_id: uuid.UUID, key: str) -> None:
        self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"suitability:{kind}:{user_id}:{key}"},
        )

    def _lock_market(self, account_id: uuid.UUID, generation: int, market: Market) -> None:
        self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"suitability:market:{account_id}:{generation}:{market.value}"},
        )

    @staticmethod
    def _require_open(application: EntitlementApplication) -> None:
        if application.status in {
            ApplicationStatus.CANCELLED_BY_USER,
            ApplicationStatus.EXPIRED,
            ApplicationStatus.REJECTED,
            ApplicationStatus.COMPLETED,
        }:
            raise SuitabilityApplicationError("application_not_open", "该申请已结束")


def _require_key(value: str) -> str:
    return _require_text(value, "idempotency_key", 128)


def _require_text(value: str, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not (cleaned := value.strip()) or len(cleaned) > maximum:
        raise SuitabilityApplicationError("invalid_input", f"{field} 不合法")
    return cleaned


def _nonnegative_decimal(value: Decimal, field: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        raise SuitabilityApplicationError("invalid_input", f"{field} 必须是非负有限数值")
    return value


def _nonnegative_int(value: int, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise SuitabilityApplicationError("invalid_input", f"{field} 必须是非负整数")
    return value
