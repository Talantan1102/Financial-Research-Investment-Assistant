from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import cast

import pytest
from app.core.database import Base
from app.models.investor_suitability import (
    ApplicationStatus,
    EntitlementApplication,
    Market,
    MarketAccessRule,
    MarketEntitlement,
    InvestorSuitabilityProfile,
    RiskDisclosureAcceptance,
    SuitabilityAssessment,
)
from app.models.paper_account import PaperAccount
from app.models.user import User
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


@pytest.fixture
def paper_account(db_session: Session) -> PaperAccount:
    for market in Market:
        db_session.add(
            MarketAccessRule(
                market=market,
                effective_from=date(2026, 7, 27),
                minimum_average_assets_20d=None,
                minimum_experience_months=None,
                required_disclosure_version=f"{market.value}-2026-07",
                rule_version="2026-07",
            )
        )
    db_session.flush()
    suffix = uuid.uuid4().hex
    user = User(
        username=f"suitability-model-{suffix}",
        email=f"suitability-model-{suffix}@example.test",
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
def application(db_session: Session, paper_account: PaperAccount) -> EntitlementApplication:
    row = EntitlementApplication.new(
        account=paper_account,
        market=Market.STAR,
        start_idempotency_key=f"start-{uuid.uuid4()}",
    )
    db_session.add(row)
    db_session.flush()
    return row


def make_paper_account(db_session: Session) -> PaperAccount:
    suffix = uuid.uuid4().hex
    user = User(
        username=f"suitability-model-{suffix}",
        email=f"suitability-model-{suffix}@example.test",
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


def make_passed_assessment(account: PaperAccount, market: Market) -> SuitabilityAssessment:
    return SuitabilityAssessment(
        account_id=account.id,
        account_generation=account.generation,
        market=market,
        submitted_snapshot={"assets": "500000.00", "experience_months": 24},
        decision="passed",
        failed_conditions=None,
        rule_version="2026-07",
    )


@pytest.mark.parametrize("fact_kind", ["assessment", "entitlement"])
def test_market_fact_rejects_a_nonexistent_rule_version(
    db_session: Session, paper_account: PaperAccount, fact_kind: str
) -> None:
    if fact_kind == "assessment":
        row = make_passed_assessment(paper_account, Market.STAR)
    else:
        row = MarketEntitlement.new(account=paper_account, market=Market.STAR)
    row.rule_version = "missing-rule-version"
    db_session.add(row)

    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("fact_kind", ["assessment", "entitlement"])
def test_market_fact_rejects_a_rule_version_from_another_market(
    db_session: Session, paper_account: PaperAccount, fact_kind: str
) -> None:
    db_session.add(
        MarketAccessRule(
            market=Market.STAR,
            effective_from=date(2026, 7, 28),
            minimum_average_assets_20d=None,
            minimum_experience_months=None,
            required_disclosure_version="star-only",
            rule_version="star-only-version",
        )
    )
    db_session.flush()
    if fact_kind == "assessment":
        row = make_passed_assessment(paper_account, Market.CHINEXT)
    else:
        row = MarketEntitlement.new(account=paper_account, market=Market.CHINEXT)
    row.rule_version = "star-only-version"
    db_session.add(row)

    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("fact_kind", ["assessment", "entitlement"])
def test_market_fact_accepts_an_existing_rule_version_for_its_market(
    db_session: Session, paper_account: PaperAccount, fact_kind: str
) -> None:
    if fact_kind == "assessment":
        row = make_passed_assessment(paper_account, Market.STAR)
    else:
        row = MarketEntitlement.new(account=paper_account, market=Market.STAR)
    db_session.add(row)

    db_session.flush()


def test_not_applied_entitlement_has_no_rule_version(
    db_session: Session, paper_account: PaperAccount
) -> None:
    row = MarketEntitlement.new(account=paper_account, market=Market.STAR)

    assert row.rule_version is None
    db_session.add(row)
    db_session.flush()


def test_not_applied_entitlement_rejects_a_rule_version(
    db_session: Session, paper_account: PaperAccount
) -> None:
    row = MarketEntitlement.new(account=paper_account, market=Market.STAR)
    row.rule_version = "2026-07"
    db_session.add(row)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_suitability_models_register_all_six_tables() -> None:
    assert {
        "investor_suitability_profiles",
        "market_access_rules",
        "suitability_assessments",
        "risk_disclosure_acceptances",
        "market_entitlements",
        "entitlement_applications",
    } <= Base.metadata.tables.keys()


def test_one_current_entitlement_per_account_and_market(
    db_session: Session, paper_account: PaperAccount
) -> None:
    db_session.add_all(
        [
            MarketEntitlement.new(account=paper_account, market=Market.STAR),
            MarketEntitlement.new(account=paper_account, market=Market.STAR),
        ]
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_cancelled_application_cannot_reference_enabled_entitlement(
    db_session: Session, application: EntitlementApplication
) -> None:
    application.status = ApplicationStatus.CANCELLED_BY_USER
    application.enabled_entitlement_id = uuid.uuid4()

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_market_rule_version_is_unique_within_market(db_session: Session) -> None:
    db_session.add_all(
        [
            MarketAccessRule(
                market=Market.STAR,
                effective_from="2026-07-27",
                minimum_average_assets_20d=Decimal("500000.00"),
                minimum_experience_months=24,
                required_disclosure_version="star-2026-01",
                rule_version="a-share-2026-07",
            ),
            MarketAccessRule(
                market=Market.STAR,
                effective_from="2026-08-01",
                minimum_average_assets_20d=Decimal("600000.00"),
                minimum_experience_months=24,
                required_disclosure_version="star-2026-08",
                rule_version="a-share-2026-07",
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_market_rule_effective_date_is_unique_within_market(db_session: Session) -> None:
    db_session.add_all(
        [
            MarketAccessRule(
                market=Market.STAR,
                effective_from=date(2026, 7, 27),
                minimum_average_assets_20d=Decimal("500000.00"),
                minimum_experience_months=24,
                required_disclosure_version="star-2026-01",
                rule_version="star-2026-07-a",
            ),
            MarketAccessRule(
                market=Market.STAR,
                effective_from=date(2026, 7, 27),
                minimum_average_assets_20d=Decimal("600000.00"),
                minimum_experience_months=24,
                required_disclosure_version="star-2026-02",
                rule_version="star-2026-07-b",
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("reference_kind", ["assessment", "entitlement"])
def test_application_cannot_reference_another_accounts_market_fact(
    db_session: Session,
    paper_account: PaperAccount,
    reference_kind: str,
) -> None:
    other_account = make_paper_account(db_session)
    application = EntitlementApplication.new(
        account=paper_account,
        market=Market.STAR,
        start_idempotency_key=f"start-{uuid.uuid4()}",
    )
    db_session.add(application)

    if reference_kind == "assessment":
        assessment = make_passed_assessment(other_account, Market.STAR)
        db_session.add(assessment)
        db_session.flush()
        application.assessment_id = assessment.id
    else:
        entitlement = MarketEntitlement.new(account=other_account, market=Market.STAR)
        db_session.add(entitlement)
        db_session.flush()
        application.enabled_entitlement_id = entitlement.id

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_application_cannot_reference_a_different_market_fact(
    db_session: Session, paper_account: PaperAccount
) -> None:
    assessment = make_passed_assessment(paper_account, Market.CHINEXT)
    db_session.add(assessment)
    db_session.flush()
    application = EntitlementApplication.new(
        account=paper_account,
        market=Market.STAR,
        start_idempotency_key=f"start-{uuid.uuid4()}",
    )
    application.assessment_id = assessment.id
    db_session.add(application)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_same_user_cannot_reuse_start_idempotency_key(
    db_session: Session, paper_account: PaperAccount
) -> None:
    db_session.add_all(
        [
            EntitlementApplication.new(
                account=paper_account,
                market=Market.STAR,
                start_idempotency_key="start-duplicate",
            ),
            EntitlementApplication.new(
                account=paper_account,
                market=Market.BSE,
                start_idempotency_key="start-duplicate",
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_same_user_cannot_reuse_confirm_idempotency_key(
    db_session: Session, paper_account: PaperAccount
) -> None:
    first = EntitlementApplication.new(
        account=paper_account,
        market=Market.STAR,
        start_idempotency_key="start-confirm-1",
    )
    second = EntitlementApplication.new(
        account=paper_account,
        market=Market.BSE,
        start_idempotency_key="start-confirm-2",
    )
    first.confirm_idempotency_key = "confirm-duplicate"
    second.confirm_idempotency_key = "confirm-duplicate"
    db_session.add_all([first, second])

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_different_users_can_reuse_idempotency_keys(
    db_session: Session, paper_account: PaperAccount
) -> None:
    other_account = make_paper_account(db_session)
    first = EntitlementApplication.new(
        account=paper_account,
        market=Market.STAR,
        start_idempotency_key="shared-start-key",
    )
    second = EntitlementApplication.new(
        account=other_account,
        market=Market.STAR,
        start_idempotency_key="shared-start-key",
    )
    first.confirm_idempotency_key = "shared-confirm-key"
    second.confirm_idempotency_key = "shared-confirm-key"
    db_session.add_all([first, second])

    db_session.flush()


def test_disclosure_acceptance_belongs_to_one_matching_application(
    db_session: Session, paper_account: PaperAccount
) -> None:
    application = EntitlementApplication.new(
        account=paper_account,
        market=Market.STAR,
        start_idempotency_key=f"start-{uuid.uuid4()}",
    )
    db_session.add(application)
    db_session.flush()
    db_session.add(
        RiskDisclosureAcceptance(
            application_id=application.id,
            account_id=paper_account.id,
            account_generation=paper_account.generation,
            market=Market.STAR,
            disclosure_version="star-2026-01",
            accepted_at=datetime.now(timezone.utc),
            source="suitability_application",
        )
    )

    db_session.flush()


def test_disclosure_acceptance_cannot_claim_a_different_application_owner(
    db_session: Session, paper_account: PaperAccount
) -> None:
    other_account = make_paper_account(db_session)
    application = EntitlementApplication.new(
        account=paper_account,
        market=Market.STAR,
        start_idempotency_key=f"start-{uuid.uuid4()}",
    )
    db_session.add(application)
    db_session.flush()
    db_session.add(
        RiskDisclosureAcceptance(
            application_id=application.id,
            account_id=other_account.id,
            account_generation=other_account.generation,
            market=Market.STAR,
            disclosure_version="star-2026-01",
            accepted_at=datetime.now(timezone.utc),
            source="suitability_application",
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_application_cannot_accept_same_disclosure_version_twice(
    db_session: Session, paper_account: PaperAccount
) -> None:
    application = EntitlementApplication.new(
        account=paper_account,
        market=Market.STAR,
        start_idempotency_key=f"start-{uuid.uuid4()}",
    )
    db_session.add(application)
    db_session.flush()
    db_session.add_all(
        [
            RiskDisclosureAcceptance(
                application_id=application.id,
                account_id=paper_account.id,
                account_generation=paper_account.generation,
                market=Market.STAR,
                disclosure_version="star-2026-01",
                accepted_at=datetime.now(timezone.utc),
                source="suitability_application",
            ),
            RiskDisclosureAcceptance(
                application_id=application.id,
                account_id=paper_account.id,
                account_generation=paper_account.generation,
                market=Market.STAR,
                disclosure_version="star-2026-01",
                accepted_at=datetime.now(timezone.utc),
                source="suitability_application",
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("submitted_snapshot", [[], "not-an-object", None])
def test_assessment_requires_a_json_object_snapshot(
    db_session: Session, paper_account: PaperAccount, submitted_snapshot: object
) -> None:
    db_session.add(
        SuitabilityAssessment(
            account_id=paper_account.id,
            account_generation=paper_account.generation,
            market=Market.STAR,
            submitted_snapshot=submitted_snapshot,
            decision="passed",
            failed_conditions=None,
            rule_version="2026-07",
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("failed_conditions", [{}, [], "not-an-array"])
def test_rejected_assessment_requires_a_nonempty_json_array_of_failed_conditions(
    db_session: Session, paper_account: PaperAccount, failed_conditions: object
) -> None:
    db_session.add(
        SuitabilityAssessment(
            account_id=paper_account.id,
            account_generation=paper_account.generation,
            market=Market.STAR,
            submitted_snapshot={"assets": "0"},
            decision="rejected",
            failed_conditions=failed_conditions,
            rule_version="2026-07",
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize(
    ("status", "completed_at", "enabled_entitlement_id"),
    [
        (ApplicationStatus.COMPLETED, None, None),
        (ApplicationStatus.CANCELLED_BY_USER, None, None),
        (ApplicationStatus.EXPIRED, None, None),
        (ApplicationStatus.REJECTED, None, None),
        (ApplicationStatus.IN_PROGRESS, datetime.now(timezone.utc), None),
        (ApplicationStatus.AWAITING_INFORMATION, datetime.now(timezone.utc), None),
        (ApplicationStatus.AWAITING_CONFIRMATION, datetime.now(timezone.utc), None),
    ],
)
def test_application_status_requires_consistent_completion_fields(
    db_session: Session,
    paper_account: PaperAccount,
    status: ApplicationStatus,
    completed_at: datetime | None,
    enabled_entitlement_id: uuid.UUID | None,
) -> None:
    db_session.add(
        EntitlementApplication(
            account_id=paper_account.id,
            account_generation=paper_account.generation,
            market=Market.STAR,
            status=status,
            start_idempotency_key=f"start-{uuid.uuid4()}",
            completed_at=completed_at,
            enabled_entitlement_id=enabled_entitlement_id,
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize(
    ("status", "can_buy", "can_sell", "can_subscribe", "enabled_at", "restricted_at"),
    [
        ("enabled", False, False, False, datetime.now(timezone.utc), None),
        ("enabled", True, False, False, None, None),
        ("not_applied", True, False, False, None, None),
        ("pending_disclosure", False, False, False, datetime.now(timezone.utc), None),
        ("revoked", False, False, False, None, datetime.now(timezone.utc)),
        ("restricted", True, True, False, datetime.now(timezone.utc), datetime.now(timezone.utc)),
        ("restricted", False, True, False, None, datetime.now(timezone.utc)),
    ],
)
def test_entitlement_status_requires_consistent_capabilities_and_timestamps(
    db_session: Session,
    paper_account: PaperAccount,
    status: str,
    can_buy: bool,
    can_sell: bool,
    can_subscribe: bool,
    enabled_at: datetime | None,
    restricted_at: datetime | None,
) -> None:
    db_session.add(
        MarketEntitlement(
            account_id=paper_account.id,
            account_generation=paper_account.generation,
            market=Market.STAR,
            status=status,
            can_buy=can_buy,
            can_sell=can_sell,
            can_subscribe=can_subscribe,
            rule_version="2026-07",
            enabled_at=enabled_at,
            restricted_at=restricted_at,
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize(
    ("declared_average_assets_20d", "securities_experience_months"),
    [
        (Decimal("-0.01"), 24),
        (Decimal("500000.00"), -1),
        (Decimal("NaN"), 24),
    ],
)
def test_profile_rejects_invalid_assets_or_experience(
    db_session: Session,
    paper_account: PaperAccount,
    declared_average_assets_20d: Decimal,
    securities_experience_months: int,
) -> None:
    db_session.add(
        InvestorSuitabilityProfile(
            user_id=paper_account.user_id,
            investor_type="ordinary_individual",
            risk_level="C3",
            declared_average_assets_20d=declared_average_assets_20d,
            securities_experience_months=securities_experience_months,
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()
