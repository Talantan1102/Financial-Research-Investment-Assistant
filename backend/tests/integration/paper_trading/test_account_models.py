from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from app.models.paper_account import (
    PaperAccount,
    PaperAccountResetAudit,
    PaperAccountStatus,
    PaperCashLedger,
    PaperHoldingLot,
)
from app.models.user import User
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session


@pytest.fixture
def user(db_session: Session) -> User:
    suffix = uuid.uuid4().hex
    row = User(
        username=f"paper-{suffix}",
        email=f"paper-{suffix}@example.test",
        hashed_password="not-used",
    )
    db_session.add(row)
    db_session.flush()
    return row


def _account(user: User, *, generation: int = 1, cash: str = "1000000") -> PaperAccount:
    return PaperAccount.new(
        user_id=user.id,
        generation=generation,
        initial_cash=Decimal(cash),
    )


def test_account_factory_sets_deterministic_financial_defaults(user: User) -> None:
    account = _account(user)

    assert account.initial_cash == Decimal("1000000.00")
    assert account.available_cash == Decimal("1000000.00")
    assert account.frozen_cash == Decimal("0.00")
    assert account.commission_rate == Decimal("0.00030000")
    assert account.minimum_commission == Decimal("5.00")
    assert account.status is PaperAccountStatus.ACTIVE
    assert account.version == 1


def test_only_one_active_account_per_user(db_session: Session, user: User) -> None:
    db_session.add(_account(user, generation=1))
    db_session.flush()
    db_session.add(_account(user, generation=2))

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_archived_generation_can_coexist_with_new_active_account(
    db_session: Session, user: User
) -> None:
    archived = _account(user, generation=1)
    archived.status = PaperAccountStatus.ARCHIVED
    active = _account(user, generation=2)
    db_session.add_all([archived, active])

    db_session.flush()

    assert db_session.query(PaperAccount).filter_by(user_id=user.id).count() == 2


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("initial_cash", Decimal("-0.01")),
        ("available_cash", Decimal("-0.01")),
        ("frozen_cash", Decimal("-0.01")),
        ("commission_rate", Decimal("-0.00000001")),
        ("minimum_commission", Decimal("-0.01")),
        ("generation", 0),
        ("version", 0),
    ],
)
def test_account_rejects_invalid_financial_or_version_values(
    db_session: Session, user: User, field: str, value: Decimal | int
) -> None:
    account = _account(user)
    setattr(account, field, value)
    db_session.add(account)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_account_rejects_unknown_status(db_session: Session, user: User) -> None:
    account = _account(user)
    account.status = "deleted"  # type: ignore[assignment]
    db_session.add(account)

    with pytest.raises(StatementError, match="not among the defined enum values"):
        db_session.flush()


def test_cash_ledger_business_key_is_unique(db_session: Session, user: User) -> None:
    account = _account(user)
    db_session.add(account)
    db_session.flush()
    entries = [
        PaperCashLedger(
            account_id=account.id,
            generation=1,
            kind="initial_deposit",
            amount=Decimal("1000000.00"),
            available_before=Decimal("0.00"),
            available_after=Decimal("1000000.00"),
            frozen_before=Decimal("0.00"),
            frozen_after=Decimal("0.00"),
            business_key="initial:account-1",
        )
        for _ in range(2)
    ]
    db_session.add(entries[0])
    db_session.flush()
    db_session.add(entries[1])

    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize(
    ("original", "remaining", "frozen"),
    [
        (-1, 0, 0),
        (100, -1, 0),
        (100, 100, -1),
        (100, 100, 101),
        (100, 101, 0),
    ],
)
def test_holding_lot_rejects_invalid_quantities(
    db_session: Session,
    user: User,
    original: int,
    remaining: int,
    frozen: int,
) -> None:
    account = _account(user)
    db_session.add(account)
    db_session.flush()
    db_session.add(
        PaperHoldingLot(
            account_id=account.id,
            generation=account.generation,
            ts_code="600519.SH",
            name="贵州茅台",
            source_fill_id=uuid.uuid4(),
            original_quantity=original,
            remaining_quantity=remaining,
            frozen_quantity=frozen,
            unit_cost=Decimal("1500.0000"),
            available_on=date(2026, 7, 20),
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_reset_audit_persists_confirmation_source_and_summary(
    db_session: Session, user: User
) -> None:
    old = _account(user, generation=1)
    old.status = PaperAccountStatus.ARCHIVED
    new = _account(user, generation=2, cash="800000")
    db_session.add_all([old, new])
    db_session.flush()
    audit = PaperAccountResetAudit(
        old_account_id=old.id,
        new_account_id=new.id,
        old_generation=old.generation,
        new_generation=new.generation,
        source_session_id="session-1",
        confirmation_id="confirm-1",
        pre_reset_summary={"available_cash": "1000000.00", "open_orders": 0},
    )
    db_session.add(audit)
    db_session.flush()
    db_session.expire(audit)

    loaded = db_session.get(PaperAccountResetAudit, audit.id)

    assert loaded is not None
    assert loaded.old_account_id == old.id
    assert loaded.new_account_id == new.id
    assert loaded.source_session_id == "session-1"
    assert loaded.confirmation_id == "confirm-1"
    assert loaded.pre_reset_summary["available_cash"] == "1000000.00"
    assert loaded.created_at is not None
