from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import cast

import pytest
from app.models.paper_account import (
    PaperAccount,
    PaperAccountResetAudit,
    PaperAccountStatus,
    PaperCashLedger,
    PaperHoldingLot,
)
from app.models.paper_order import OrderSide, OrderStatus, OrderType, PaperFill, PaperOrder
from app.models.user import User
from sqlalchemy import Engine, delete, text
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm.exc import StaleDataError


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
        user_id=cast(uuid.UUID, user.id),
        generation=generation,
        initial_cash=Decimal(cash),
    )


def _persist_source_fill(db_session: Session, user: User, account: PaperAccount) -> uuid.UUID:
    now = datetime.now(UTC)
    order = PaperOrder(
        account_id=account.id,
        account_generation=account.generation,
        user_id=user.id,
        client_request_id=f"request-{uuid.uuid4()}",
        source_session_id="session-1",
        source_message_id="message-1",
        ts_code="600519.SH",
        name="贵州茅台",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=100,
        limit_price=Decimal("1500.00"),
        filled_quantity=100,
        avg_fill_price=Decimal("1500.00"),
        status=OrderStatus.FILLED,
        original_proposal={"quantity": 100},
        confirmed_payload={"quantity": 100},
        user_edits={},
        quote_snapshot={"latest_price": "1500.00", "timestamp": now.isoformat()},
        rules_version="cn-a-20260706",
        expires_at=now + timedelta(minutes=5),
        confirmed_at=now,
        completed_at=now,
    )
    db_session.add(order)
    db_session.flush()
    fill = PaperFill(
        order_id=order.id,
        fill_seq=1,
        quantity=100,
        price=Decimal("1500.00"),
        gross_amount=Decimal("150000.00"),
        commission=Decimal("45.00"),
        stamp_duty=Decimal("0.00"),
        transfer_fee=Decimal("1.50"),
        quote_timestamp=now,
        quote_source="fixed-test-quote",
        executed_at=now,
        trade_id=uuid.uuid4(),
    )
    db_session.add(fill)
    db_session.flush()
    return cast(uuid.UUID, fill.id)


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
    archived.status = PaperAccountStatus.ARCHIVED  # type: ignore[assignment]
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
        ("commission_rate", Decimal("1.00000000")),
        ("minimum_commission", Decimal("-0.01")),
        ("generation", 0),
    ],
)
def test_account_rejects_invalid_financial_or_generation_values(
    db_session: Session, user: User, field: str, value: Decimal | int
) -> None:
    account = _account(user)
    setattr(account, field, value)
    db_session.add(account)

    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize(
    "field",
    [
        "initial_cash",
        "available_cash",
        "frozen_cash",
        "commission_rate",
        "minimum_commission",
    ],
)
@pytest.mark.parametrize("special", ["NaN", "Infinity", "-Infinity"])
def test_account_rejects_nonfinite_financial_values(
    db_session: Session, user: User, field: str, special: str
) -> None:
    account = _account(user)
    setattr(account, field, Decimal(special))
    db_session.add(account)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_database_rejects_nonpositive_account_version(db_session: Session, user: User) -> None:
    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                """
                INSERT INTO paper_accounts (
                    id, user_id, generation, initial_cash, available_cash, frozen_cash,
                    commission_rate, minimum_commission, status, version
                ) VALUES (
                    :id, :user_id, 1, 1000000, 1000000, 0, 0.0003, 5, 'active', 0
                )
                """
            ),
            {"id": uuid.uuid4(), "user_id": user.id},
        )


def test_account_rejects_unknown_status(db_session: Session, user: User) -> None:
    account = _account(user)
    account.status = "deleted"  # type: ignore[assignment]
    db_session.add(account)

    with pytest.raises(StatementError, match="not among the defined enum values"):
        db_session.flush()


def test_zero_commission_rate_is_valid(db_session: Session, user: User) -> None:
    account = _account(user)
    account.commission_rate = Decimal("0")  # type: ignore[assignment]
    db_session.add(account)

    db_session.flush()


def _create_committed_account(engine: Engine) -> tuple[uuid.UUID, uuid.UUID]:
    session = Session(engine, expire_on_commit=False)
    try:
        suffix = uuid.uuid4().hex
        row = User(
            username=f"paper-version-{suffix}",
            email=f"paper-version-{suffix}@example.test",
            hashed_password="not-used",
        )
        session.add(row)
        session.flush()
        account = _account(row)
        session.add(account)
        session.commit()
        return cast(uuid.UUID, row.id), cast(uuid.UUID, account.id)
    finally:
        session.close()


def _delete_committed_account(engine: Engine, user_id: uuid.UUID, account_id: uuid.UUID) -> None:
    with Session(engine) as session:
        session.execute(delete(PaperAccount).where(PaperAccount.id == account_id))
        session.execute(delete(User).where(User.id == user_id))
        session.commit()


def test_account_update_increments_optimistic_version(pg_test_engine: Engine) -> None:
    user_id, account_id = _create_committed_account(pg_test_engine)
    try:
        with Session(pg_test_engine, expire_on_commit=False) as session:
            account = session.get(PaperAccount, account_id)
            assert account is not None
            account.available_cash = Decimal("999999.00")  # type: ignore[assignment]
            session.commit()

            assert account.version == 2
    finally:
        _delete_committed_account(pg_test_engine, user_id, account_id)


def test_second_stale_account_writer_is_rejected(pg_test_engine: Engine) -> None:
    user_id, account_id = _create_committed_account(pg_test_engine)
    first_factory = sessionmaker(bind=pg_test_engine, expire_on_commit=False)
    second_factory = sessionmaker(bind=pg_test_engine, expire_on_commit=False)
    first = first_factory()
    second = second_factory()
    try:
        first_account = first.get(PaperAccount, account_id)
        stale_account = second.get(PaperAccount, account_id)
        assert first_account is not None
        assert stale_account is not None

        first_account.available_cash = Decimal("900000.00")  # type: ignore[assignment]
        first.commit()
        stale_account.available_cash = Decimal("800000.00")  # type: ignore[assignment]

        with pytest.raises(StaleDataError):
            second.commit()
        second.rollback()
    finally:
        first.close()
        second.close()
        _delete_committed_account(pg_test_engine, user_id, account_id)


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


def test_cash_ledger_generation_must_match_account(db_session: Session, user: User) -> None:
    account = _account(user)
    db_session.add(account)
    db_session.flush()
    db_session.add(
        PaperCashLedger(
            account_id=account.id,
            generation=2,
            kind="initial_deposit",
            amount=Decimal("1000000.00"),
            available_before=Decimal("0.00"),
            available_after=Decimal("1000000.00"),
            frozen_before=Decimal("0.00"),
            frozen_after=Decimal("0.00"),
            business_key="wrong-generation",
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize(
    "field",
    ["amount", "available_before", "available_after", "frozen_before", "frozen_after"],
)
@pytest.mark.parametrize("special", ["NaN", "Infinity", "-Infinity"])
def test_cash_ledger_rejects_nonfinite_financial_values(
    db_session: Session, user: User, field: str, special: str
) -> None:
    account = _account(user)
    db_session.add(account)
    db_session.flush()
    entry = PaperCashLedger(
        account_id=account.id,
        generation=1,
        kind="cash_adjustment",
        amount=Decimal("0.00"),
        available_before=Decimal("1000000.00"),
        available_after=Decimal("1000000.00"),
        frozen_before=Decimal("0.00"),
        frozen_after=Decimal("0.00"),
        business_key=f"nonfinite:{field}:{special}",
    )
    setattr(entry, field, Decimal(special))
    db_session.add(entry)

    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize(
    ("original", "remaining", "frozen"),
    [
        (-1, 0, 0),
        (0, 0, 0),
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
    source_fill_id = _persist_source_fill(db_session, user, account)
    db_session.add(
        PaperHoldingLot(
            account_id=account.id,
            generation=account.generation,
            ts_code="600519.SH",
            name="贵州茅台",
            source_fill_id=source_fill_id,
            original_quantity=original,
            remaining_quantity=remaining,
            frozen_quantity=frozen,
            unit_cost=Decimal("1500.0000"),
            available_on=date(2026, 7, 20),
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("unit_cost", [Decimal("0"), Decimal("-0.0001")])
def test_holding_lot_rejects_nonpositive_unit_cost(
    db_session: Session, user: User, unit_cost: Decimal
) -> None:
    account = _account(user)
    db_session.add(account)
    db_session.flush()
    source_fill_id = _persist_source_fill(db_session, user, account)
    db_session.add(
        PaperHoldingLot(
            account_id=account.id,
            generation=1,
            ts_code="600519.SH",
            name="贵州茅台",
            source_fill_id=source_fill_id,
            original_quantity=100,
            remaining_quantity=100,
            frozen_quantity=0,
            unit_cost=unit_cost,
            available_on=date(2026, 7, 20),
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("special", ["NaN", "Infinity", "-Infinity"])
def test_holding_lot_rejects_nonfinite_unit_cost(
    db_session: Session, user: User, special: str
) -> None:
    account = _account(user)
    db_session.add(account)
    db_session.flush()
    source_fill_id = _persist_source_fill(db_session, user, account)
    db_session.add(
        PaperHoldingLot(
            account_id=account.id,
            generation=1,
            ts_code="600519.SH",
            name="贵州茅台",
            source_fill_id=source_fill_id,
            original_quantity=100,
            remaining_quantity=100,
            frozen_quantity=0,
            unit_cost=Decimal(special),
            available_on=date(2026, 7, 20),
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_fully_consumed_holding_lot_is_valid(db_session: Session, user: User) -> None:
    account = _account(user)
    db_session.add(account)
    db_session.flush()
    source_fill_id = _persist_source_fill(db_session, user, account)
    db_session.add(
        PaperHoldingLot(
            account_id=account.id,
            generation=1,
            ts_code="600519.SH",
            name="贵州茅台",
            source_fill_id=source_fill_id,
            original_quantity=100,
            remaining_quantity=0,
            frozen_quantity=0,
            unit_cost=Decimal("1500.0000"),
            available_on=date(2026, 7, 20),
        )
    )

    db_session.flush()


def test_holding_lot_generation_must_match_account(db_session: Session, user: User) -> None:
    account = _account(user)
    db_session.add(account)
    db_session.flush()
    source_fill_id = _persist_source_fill(db_session, user, account)
    db_session.add(
        PaperHoldingLot(
            account_id=account.id,
            generation=2,
            ts_code="600519.SH",
            name="贵州茅台",
            source_fill_id=source_fill_id,
            original_quantity=100,
            remaining_quantity=100,
            frozen_quantity=0,
            unit_cost=Decimal("1500.0000"),
            available_on=date(2026, 7, 20),
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_holding_lot_source_fill_is_unique(db_session: Session, user: User) -> None:
    account = _account(user)
    db_session.add(account)
    db_session.flush()
    source_fill_id = _persist_source_fill(db_session, user, account)
    for ts_code in ("600519.SH", "000001.SZ"):
        db_session.add(
            PaperHoldingLot(
                account_id=account.id,
                generation=1,
                ts_code=ts_code,
                name="stock",
                source_fill_id=source_fill_id,
                original_quantity=100,
                remaining_quantity=100,
                frozen_quantity=0,
                unit_cost=Decimal("10.0000"),
                available_on=date(2026, 7, 20),
            )
        )
        if ts_code == "600519.SH":
            db_session.flush()

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_holding_lot_rejects_dangling_source_fill(db_session: Session, user: User) -> None:
    account = _account(user)
    db_session.add(account)
    db_session.flush()
    db_session.add(
        PaperHoldingLot(
            account_id=account.id,
            generation=1,
            ts_code="600519.SH",
            name="贵州茅台",
            source_fill_id=uuid.uuid4(),
            original_quantity=100,
            remaining_quantity=100,
            frozen_quantity=0,
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
    old.status = PaperAccountStatus.ARCHIVED  # type: ignore[assignment]
    new = _account(user, generation=2, cash="800000")
    db_session.add_all([old, new])
    db_session.flush()
    audit = PaperAccountResetAudit(
        user_id=user.id,
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


def _reset_pair(db_session: Session, user: User, *, new_generation: int = 2):
    old = _account(user, generation=1)
    old.status = PaperAccountStatus.ARCHIVED  # type: ignore[assignment]
    new = _account(user, generation=new_generation, cash="800000")
    db_session.add_all([old, new])
    db_session.flush()
    return old, new


def _reset_audit(
    user: User,
    old: PaperAccount,
    new: PaperAccount,
    *,
    source_session_id: str = "session-1",
    confirmation_id: str = "confirm-1",
) -> PaperAccountResetAudit:
    return PaperAccountResetAudit(
        user_id=user.id,
        old_account_id=old.id,
        new_account_id=new.id,
        old_generation=old.generation,
        new_generation=new.generation,
        source_session_id=source_session_id,
        confirmation_id=confirmation_id,
        pre_reset_summary={"available_cash": "1000000.00"},
    )


def test_reset_audit_rejects_generation_mismatch(db_session: Session, user: User) -> None:
    old, new = _reset_pair(db_session, user)
    audit = _reset_audit(user, old, new)
    audit.old_generation = 2  # type: ignore[assignment]
    audit.new_generation = 3  # type: ignore[assignment]
    db_session.add(audit)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_reset_audit_rejects_cross_user_accounts(db_session: Session, user: User) -> None:
    old, _ = _reset_pair(db_session, user)
    suffix = uuid.uuid4().hex
    other_user = User(
        username=f"paper-other-{suffix}",
        email=f"paper-other-{suffix}@example.test",
        hashed_password="not-used",
    )
    db_session.add(other_user)
    db_session.flush()
    other_new = _account(other_user, generation=2)
    db_session.add(other_new)
    db_session.flush()
    db_session.add(_reset_audit(user, old, other_new))

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_reset_audit_rejects_same_account(db_session: Session, user: User) -> None:
    old = _account(user)
    old.status = PaperAccountStatus.ARCHIVED  # type: ignore[assignment]
    db_session.add(old)
    db_session.flush()
    db_session.add(_reset_audit(user, old, old))

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_reset_audit_requires_next_generation(db_session: Session, user: User) -> None:
    old, new = _reset_pair(db_session, user, new_generation=3)
    db_session.add(_reset_audit(user, old, new))

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_reset_confirmation_is_idempotent(db_session: Session, user: User) -> None:
    old, new = _reset_pair(db_session, user)
    db_session.add(_reset_audit(user, old, new))
    db_session.flush()
    db_session.add(_reset_audit(user, old, new))

    with pytest.raises(IntegrityError):
        db_session.flush()
