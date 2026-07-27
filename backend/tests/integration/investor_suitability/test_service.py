from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from typing import cast

import pytest
from app.models.investor_suitability import (
    ApplicationStatus,
    EntitlementApplication,
    EntitlementStatus,
    Market,
    MarketAccessRule,
    MarketEntitlement,
)
from app.models.paper_account import PaperAccount
from app.models.user import User
from app.services.investor_suitability.rules import rulebook
from app.services.investor_suitability.service import (
    SuitabilityApplicationError,
    SuitabilityApplicationService,
)
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture
def account(db_session: Session) -> PaperAccount:
    for rule in rulebook().rules:
        db_session.add(
            MarketAccessRule(
                market=rule.market,
                effective_from=date(2026, 7, 27),
                minimum_average_assets_20d=rule.minimum_average_assets_20d,
                minimum_experience_months=rule.minimum_experience_months,
                required_disclosure_version=rule.required_disclosure_version,
                rule_version=rule.rule_version,
            )
        )
    suffix = uuid.uuid4().hex[:12]
    user = User(
        username=f"suitability-service-{suffix}",
        email=f"suitability-service-{suffix}@example.test",
        hashed_password="not-used",
    )
    db_session.add(user)
    db_session.flush()
    account = PaperAccount.new(
        user_id=cast(uuid.UUID, user.id),
        generation=1,
        initial_cash=Decimal("1000000.00"),
    )
    db_session.add(account)
    db_session.flush()
    return account


@pytest.fixture
def service(db_session: Session) -> SuitabilityApplicationService:
    return SuitabilityApplicationService(db_session)


def _eligible_application(
    service: SuitabilityApplicationService, account: PaperAccount
) -> EntitlementApplication:
    application = service.start(
        user_id=account.user_id,
        account_id=account.id,
        market=Market.STAR,
        idempotency_key="start-star",
    )
    service.submit_profile(
        user_id=account.user_id,
        application_id=application.id,
        average_assets_20d=Decimal("500000.00"),
        experience_months=24,
        risk_level="C4",
    )
    return application


def test_start_is_idempotent_for_one_user_and_locks_active_generation(
    service: SuitabilityApplicationService, account: PaperAccount
) -> None:
    first = service.start(
        user_id=account.user_id,
        account_id=account.id,
        market=Market.STAR,
        idempotency_key="same-start",
    )
    replay = service.start(
        user_id=account.user_id,
        account_id=account.id,
        market=Market.STAR,
        idempotency_key="same-start",
    )

    assert replay.id == first.id
    assert first.account_generation == account.generation
    assert first.status is ApplicationStatus.IN_PROGRESS


def test_confirm_atomically_records_disclosure_and_enables_permission(
    service: SuitabilityApplicationService, account: PaperAccount
) -> None:
    application = _eligible_application(service, account)

    entitlement = service.confirm(
        user_id=account.user_id,
        application_id=application.id,
        disclosure_version="star-risk-disclosure-2026-07",
        idempotency_key="confirm-1",
    )

    assert entitlement.status is EntitlementStatus.ENABLED
    assert entitlement.can_buy is True
    assert entitlement.can_sell is True
    assert entitlement.can_subscribe is True
    assert service.disclosure_for(application.id).accepted_at is not None
    assert application.status is ApplicationStatus.COMPLETED
    assert application.enabled_entitlement_id == entitlement.id


def test_confirm_replay_returns_the_same_enabled_entitlement(
    service: SuitabilityApplicationService, account: PaperAccount
) -> None:
    application = _eligible_application(service, account)
    first = service.confirm(
        user_id=account.user_id,
        application_id=application.id,
        disclosure_version="star-risk-disclosure-2026-07",
        idempotency_key="confirm-1",
    )
    replay = service.confirm(
        user_id=account.user_id,
        application_id=application.id,
        disclosure_version="star-risk-disclosure-2026-07",
        idempotency_key="confirm-1",
    )

    assert replay.id == first.id


def test_confirm_replay_rejects_a_different_disclosure_version(
    service: SuitabilityApplicationService, account: PaperAccount
) -> None:
    application = _eligible_application(service, account)
    service.confirm(
        user_id=account.user_id,
        application_id=application.id,
        disclosure_version="star-risk-disclosure-2026-07",
        idempotency_key="confirm-1",
    )

    with pytest.raises(SuitabilityApplicationError) as error:
        service.confirm(
            user_id=account.user_id,
            application_id=application.id,
            disclosure_version="star-risk-disclosure-old",
            idempotency_key="confirm-1",
        )

    assert error.value.code == "idempotency_conflict"


def test_confirm_rejects_stale_disclosure_version(
    service: SuitabilityApplicationService, account: PaperAccount
) -> None:
    application = _eligible_application(service, account)

    with pytest.raises(SuitabilityApplicationError, match="风险揭示书版本") as error:
        service.confirm(
            user_id=account.user_id,
            application_id=application.id,
            disclosure_version="star-risk-disclosure-old",
            idempotency_key="confirm-1",
        )

    assert error.value.code == "stale_disclosure_version"
    assert service.disclosure_for(application.id) is None
    assert service.entitlement_for(account.id, Market.STAR) is None


def test_confirm_rechecks_the_stored_profile_before_enabling(
    service: SuitabilityApplicationService, account: PaperAccount
) -> None:
    application = service.start(
        user_id=account.user_id,
        account_id=account.id,
        market=Market.STAR,
        idempotency_key="start-star",
    )
    assessment = service.submit_profile(
        user_id=account.user_id,
        application_id=application.id,
        average_assets_20d=Decimal("499999.99"),
        experience_months=24,
        risk_level="C4",
    )

    assert assessment.decision.value == "rejected"
    with pytest.raises(SuitabilityApplicationError) as error:
        service.confirm(
            user_id=account.user_id,
            application_id=application.id,
            disclosure_version="star-risk-disclosure-2026-07",
            idempotency_key="confirm-1",
        )

    assert error.value.code == "application_not_eligible"
    assert application.status is ApplicationStatus.REJECTED
    assert application.confirm_idempotency_key == "confirm-1"
    with pytest.raises(SuitabilityApplicationError) as replay_error:
        service.confirm(
            user_id=account.user_id,
            application_id=application.id,
            disclosure_version="star-risk-disclosure-2026-07",
            idempotency_key="confirm-1",
        )
    assert replay_error.value.code == "application_not_eligible"
    assert service.entitlement_for(account.id, Market.STAR) is None


def test_start_rejects_an_already_enabled_market(
    service: SuitabilityApplicationService, account: PaperAccount
) -> None:
    application = _eligible_application(service, account)
    service.confirm(
        user_id=account.user_id,
        application_id=application.id,
        disclosure_version="star-risk-disclosure-2026-07",
        idempotency_key="confirm-1",
    )

    with pytest.raises(SuitabilityApplicationError) as error:
        service.start(
            user_id=account.user_id,
            account_id=account.id,
            market=Market.STAR,
            idempotency_key="start-after-enabled",
        )

    assert error.value.code == "market_already_enabled"


def test_cancel_never_creates_disclosure_or_permission(
    service: SuitabilityApplicationService, account: PaperAccount
) -> None:
    application = service.start(
        user_id=account.user_id,
        account_id=account.id,
        market=Market.STAR,
        idempotency_key="start-star",
    )

    cancelled = service.cancel(user_id=account.user_id, application_id=application.id)

    assert cancelled.status is ApplicationStatus.CANCELLED_BY_USER
    assert service.disclosure_for(application.id) is None
    assert service.entitlement_for(account.id, Market.STAR) is None


def test_list_entitlements_is_user_scoped(
    service: SuitabilityApplicationService, account: PaperAccount, db_session: Session
) -> None:
    application = _eligible_application(service, account)
    enabled = service.confirm(
        user_id=account.user_id,
        application_id=application.id,
        disclosure_version="star-risk-disclosure-2026-07",
        idempotency_key="confirm-1",
    )

    assert [item.id for item in service.list_entitlements(user_id=account.user_id, account_id=account.id)] == [enabled.id]
    assert db_session.scalar(select(MarketEntitlement).where(MarketEntitlement.id == enabled.id)) is not None


def test_concurrent_confirmation_creates_at_most_one_enabled_entitlement(
    pg_test_engine,
) -> None:
    """Two requests for one account/market serialize on the durable market lock."""
    factory = sessionmaker(bind=pg_test_engine, expire_on_commit=False)
    with factory.begin() as seed:
        for rule in rulebook().rules:
            seed.add(
                MarketAccessRule(
                    market=rule.market,
                    effective_from=date(2026, 7, 27),
                    minimum_average_assets_20d=rule.minimum_average_assets_20d,
                    minimum_experience_months=rule.minimum_experience_months,
                    required_disclosure_version=rule.required_disclosure_version,
                    rule_version=rule.rule_version,
                )
            )
        suffix = uuid.uuid4().hex[:12]
        user = User(
            username=f"suitability-race-{suffix}",
            email=f"suitability-race-{suffix}@example.test",
            hashed_password="not-used",
        )
        seed.add(user)
        seed.flush()
        account = PaperAccount.new(
            user_id=cast(uuid.UUID, user.id), generation=1, initial_cash=Decimal("1000000")
        )
        seed.add(account)
        seed.flush()
        service = SuitabilityApplicationService(seed)
        applications = [
            service.start(
                user_id=account.user_id,
                account_id=account.id,
                market=Market.STAR,
                idempotency_key=f"start-{number}",
            )
            for number in (1, 2)
        ]
        for application in applications:
            service.submit_profile(
                user_id=account.user_id,
                application_id=application.id,
                average_assets_20d=Decimal("500000"),
                experience_months=24,
                risk_level="C4",
            )
        user_id, account_id = account.user_id, account.id
        application_ids = [application.id for application in applications]

    def confirm(application_id: uuid.UUID, key: str) -> str:
        with factory.begin() as session:
            try:
                SuitabilityApplicationService(session).confirm(
                    user_id=user_id,
                    application_id=application_id,
                    disclosure_version="star-risk-disclosure-2026-07",
                    idempotency_key=key,
                )
                return "enabled"
            except SuitabilityApplicationError as error:
                return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda item: confirm(*item), zip(application_ids, ("confirm-1", "confirm-2"))))

    with factory() as verify:
        enabled = verify.scalars(
            select(MarketEntitlement).where(
                MarketEntitlement.account_id == account_id,
                MarketEntitlement.market == Market.STAR,
                MarketEntitlement.status == EntitlementStatus.ENABLED,
            )
        ).all()
    assert outcomes.count("enabled") == 1
    assert len(enabled) == 1
