# ruff: noqa: B010
# Legacy SQLAlchemy Column typing requires setattr in mutation-focused tests.

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta, tzinfo
from decimal import Decimal
from typing import cast

import pytest
from app.models.paper_account import PaperAccount, PaperAccountStatus
from app.models.paper_order import (
    OrderSide,
    OrderStatus,
    OrderType,
    PaperFill,
    PaperMatchPass,
    PaperOrder,
)
from app.models.user import User
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session


class _IndeterminateTimezone(tzinfo):
    def utcoffset(self, dt: datetime | None) -> None:
        return None

    def dst(self, dt: datetime | None) -> None:
        return None

    def tzname(self, dt: datetime | None) -> None:
        return None


@pytest.fixture
def user(db_session: Session) -> User:
    suffix = uuid.uuid4().hex
    row = User(
        username=f"paper-order-{suffix}",
        email=f"paper-order-{suffix}@example.test",
        hashed_password="not-used",
    )
    db_session.add(row)
    db_session.flush()
    return row


def _account(
    db_session: Session,
    user: User,
    *,
    generation: int = 1,
    archived: bool = False,
) -> PaperAccount:
    account = PaperAccount.new(
        user_id=cast(uuid.UUID, user.id),
        generation=generation,
        initial_cash=Decimal("1000000.00"),
    )
    if archived:
        account.status = PaperAccountStatus.ARCHIVED  # type: ignore[assignment]
    db_session.add(account)
    db_session.flush()
    return account


def _order(
    *,
    account: PaperAccount,
    user: User,
    client_request_id: str | None = None,
    order_type: OrderType = OrderType.LIMIT,
    limit_price: Decimal | None = Decimal("1500.00"),
    quantity: int = 100,
    filled_quantity: int = 0,
    avg_fill_price: Decimal | None = None,
    status: OrderStatus = OrderStatus.AWAITING_CONFIRMATION,
    completed_at: datetime | None = None,
    confirmed_payload: dict[str, object] | None = None,
    confirmed_at: datetime | None = None,
    reject_code: str | None = None,
    reject_message: str | None = None,
    proposal_fingerprint: str | None = None,
) -> PaperOrder:
    now = datetime.now(UTC)
    return PaperOrder(
        account_id=account.id,
        account_generation=account.generation,
        user_id=user.id,
        client_request_id=client_request_id,
        source_session_id="session-1",
        source_message_id="message-1",
        proposal_fingerprint=proposal_fingerprint or uuid.uuid4().hex * 2,
        ts_code="600519.SH",
        name="贵州茅台",
        side=OrderSide.BUY,
        order_type=order_type,
        quantity=quantity,
        limit_price=limit_price,
        filled_quantity=filled_quantity,
        avg_fill_price=avg_fill_price,
        status=status,
        original_proposal={"quantity": quantity},
        confirmed_payload=confirmed_payload,
        user_edits=None,
        quote_snapshot={"latest_price": "1499.00", "timestamp": now.isoformat()},
        rules_version="cn-a-20260706",
        reject_code=reject_code,
        reject_message=reject_message,
        expires_at=now + timedelta(minutes=5),
        confirmed_at=confirmed_at,
        completed_at=completed_at,
    )


def _fill(
    order: PaperOrder,
    *,
    fill_seq: int = 1,
    trade_id: uuid.UUID | None = None,
    quantity: int = 100,
    price: Decimal = Decimal("1500.00"),
    commission: Decimal = Decimal("45.00"),
) -> PaperFill:
    now = datetime.now(UTC)
    return PaperFill(
        order_id=order.id,
        fill_seq=fill_seq,
        quantity=quantity,
        price=price,
        gross_amount=price * quantity,
        commission=commission,
        stamp_duty=Decimal("0.00"),
        transfer_fee=Decimal("1.50"),
        quote_timestamp=now,
        quote_source="fixed-test-quote",
        executed_at=now,
        trade_id=trade_id or uuid.uuid4(),
    )


def test_order_enums_have_exact_business_values() -> None:
    assert [member.value for member in OrderSide] == ["buy", "sell"]
    assert [member.value for member in OrderType] == ["market", "limit"]
    assert [member.value for member in OrderStatus] == [
        "awaiting_confirmation",
        "queued",
        "open",
        "partially_filled",
        "filled",
        "cancelled",
        "expired",
        "rejected",
    ]


def test_order_persists_full_prepared_payload(db_session: Session, user: User) -> None:
    account = _account(db_session, user)
    order = _order(account=account, user=user)
    db_session.add(order)
    db_session.flush()
    db_session.expire(order)

    loaded = db_session.get(PaperOrder, order.id)

    assert loaded is not None
    assert loaded.account_generation == 1
    assert loaded.client_request_id is None
    assert loaded.original_proposal == {"quantity": 100}
    assert loaded.confirmed_payload is None
    assert loaded.user_edits is None
    assert loaded.quote_snapshot["latest_price"] == "1499.00"
    assert loaded.created_at is not None
    assert loaded.confirmed_at is None


@pytest.mark.parametrize("field", ["original_proposal", "quote_snapshot"])
def test_order_rejects_none_for_required_snapshots(
    db_session: Session, user: User, field: str
) -> None:
    account = _account(db_session, user)
    order = _order(account=account, user=user)
    setattr(order, field, None)
    db_session.add(order)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_prepare_allows_multiple_null_confirmation_keys(db_session: Session, user: User) -> None:
    account = _account(db_session, user)
    db_session.add_all([_order(account=account, user=user), _order(account=account, user=user)])

    db_session.flush()


def test_confirmation_key_is_unique_per_user_when_nonnull(db_session: Session, user: User) -> None:
    account = _account(db_session, user)
    first = _order(account=account, user=user, client_request_id="request-1")
    setattr(first, "status", OrderStatus.OPEN)
    setattr(first, "confirmed_payload", {"quantity": 100})
    setattr(first, "confirmed_at", datetime.now(UTC))
    db_session.add(first)
    db_session.flush()
    duplicate = _order(account=account, user=user, client_request_id="request-1")
    setattr(duplicate, "status", OrderStatus.OPEN)
    setattr(duplicate, "confirmed_payload", {"quantity": 100})
    setattr(duplicate, "confirmed_at", datetime.now(UTC))
    db_session.add(duplicate)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_proposal_fingerprint_is_unique_within_exact_account_generation(
    db_session: Session, user: User
) -> None:
    account = _account(db_session, user)
    fingerprint = "a" * 64
    db_session.add(_order(account=account, user=user, proposal_fingerprint=fingerprint))
    db_session.flush()
    db_session.add(_order(account=account, user=user, proposal_fingerprint=fingerprint))

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_confirmation_key_cannot_be_blank(db_session: Session, user: User) -> None:
    account = _account(db_session, user)
    order = _order(account=account, user=user, client_request_id="   ")
    setattr(order, "status", OrderStatus.OPEN)
    setattr(order, "confirmed_payload", {"quantity": 100})
    setattr(order, "confirmed_at", datetime.now(UTC))
    db_session.add(order)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_same_confirmation_key_is_independent_between_users(
    db_session: Session, user: User
) -> None:
    first_account = _account(db_session, user)
    suffix = uuid.uuid4().hex
    other = User(
        username=f"paper-order-other-{suffix}",
        email=f"paper-order-other-{suffix}@example.test",
        hashed_password="not-used",
    )
    db_session.add(other)
    db_session.flush()
    other_account = _account(db_session, other)
    first = _order(account=first_account, user=user, client_request_id="request-1")
    second = _order(account=other_account, user=other, client_request_id="request-1")
    for order in (first, second):
        setattr(order, "status", OrderStatus.OPEN)
        setattr(order, "confirmed_payload", {"quantity": 100})
        setattr(order, "confirmed_at", datetime.now(UTC))
    db_session.add_all([first, second])

    db_session.flush()


def test_order_rejects_cross_user_account_ownership(db_session: Session, user: User) -> None:
    account = _account(db_session, user)
    suffix = uuid.uuid4().hex
    other = User(
        username=f"paper-order-owner-{suffix}",
        email=f"paper-order-owner-{suffix}@example.test",
        hashed_password="not-used",
    )
    db_session.add(other)
    db_session.flush()
    db_session.add(_order(account=account, user=other))

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_order_rejects_stale_account_generation(db_session: Session, user: User) -> None:
    account = _account(db_session, user)
    order = _order(account=account, user=user)
    order.account_generation = 2  # type: ignore[assignment]
    db_session.add(order)

    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize(
    ("order_type", "limit_price"),
    [
        (OrderType.MARKET, Decimal("1500.00")),
        (OrderType.LIMIT, None),
        (OrderType.LIMIT, Decimal("0.00")),
    ],
)
def test_order_type_and_limit_price_must_agree(
    db_session: Session,
    user: User,
    order_type: OrderType,
    limit_price: Decimal | None,
) -> None:
    account = _account(db_session, user)
    db_session.add(
        _order(account=account, user=user, order_type=order_type, limit_price=limit_price)
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_market_order_without_limit_price_is_valid(db_session: Session, user: User) -> None:
    account = _account(db_session, user)
    db_session.add(
        _order(account=account, user=user, order_type=OrderType.MARKET, limit_price=None)
    )

    db_session.flush()


@pytest.mark.parametrize(
    ("quantity", "filled_quantity", "avg_fill_price"),
    [
        (0, 0, None),
        (100, -1, None),
        (100, 101, Decimal("1500.00")),
        (100, 1, None),
        (100, 0, Decimal("1500.00")),
        (100, 1, Decimal("0.00")),
    ],
)
def test_order_rejects_invalid_quantity_or_fill_average(
    db_session: Session,
    user: User,
    quantity: int,
    filled_quantity: int,
    avg_fill_price: Decimal | None,
) -> None:
    account = _account(db_session, user)
    db_session.add(
        _order(
            account=account,
            user=user,
            quantity=quantity,
            filled_quantity=filled_quantity,
            avg_fill_price=avg_fill_price,
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_rejected_order_requires_reject_details_and_completion_time(
    db_session: Session, user: User
) -> None:
    account = _account(db_session, user)
    db_session.add(
        _order(
            account=account,
            user=user,
            client_request_id="request-1",
            status=OrderStatus.REJECTED,
            confirmed_payload={"quantity": 100},
            confirmed_at=datetime.now(UTC),
            reject_code=None,
            reject_message=None,
            completed_at=datetime.now(UTC),
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_non_rejected_order_cannot_carry_reject_details(db_session: Session, user: User) -> None:
    account = _account(db_session, user)
    db_session.add(
        _order(
            account=account,
            user=user,
            reject_code="insufficient_cash",
            reject_message="余额不足",
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_terminal_order_requires_completion_time(db_session: Session, user: User) -> None:
    account = _account(db_session, user)
    db_session.add(
        _order(
            account=account,
            user=user,
            status=OrderStatus.FILLED,
            filled_quantity=100,
            avg_fill_price=Decimal("1500.00"),
            client_request_id="request-1",
            confirmed_payload={"quantity": 100},
            confirmed_at=datetime.now(UTC),
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize(
    ("status", "filled_quantity", "avg_fill_price"),
    [
        (OrderStatus.FILLED, 99, Decimal("1500.00")),
        (OrderStatus.PARTIALLY_FILLED, 0, None),
        (OrderStatus.PARTIALLY_FILLED, 100, Decimal("1500.00")),
    ],
)
def test_active_fill_status_agrees_with_filled_quantity(
    db_session: Session,
    user: User,
    status: OrderStatus,
    filled_quantity: int,
    avg_fill_price: Decimal | None,
) -> None:
    account = _account(db_session, user)
    completed_at = datetime.now(UTC) if status is OrderStatus.FILLED else None
    db_session.add(
        _order(
            account=account,
            user=user,
            client_request_id="request-1",
            status=status,
            filled_quantity=filled_quantity,
            avg_fill_price=avg_fill_price,
            completed_at=completed_at,
            confirmed_payload={"quantity": 100},
            confirmed_at=datetime.now(UTC),
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def _confirmation_fields() -> dict[str, object]:
    return {
        "client_request_id": "request-1",
        "confirmed_payload": {"quantity": 100},
        "confirmed_at": datetime.now(UTC),
    }


@pytest.mark.parametrize(
    "status",
    [
        OrderStatus.AWAITING_CONFIRMATION,
        OrderStatus.QUEUED,
        OrderStatus.OPEN,
        OrderStatus.REJECTED,
    ],
)
def test_zero_fill_state_rejects_positive_filled_quantity(
    db_session: Session, user: User, status: OrderStatus
) -> None:
    account = _account(db_session, user)
    order = _order(
        account=account,
        user=user,
        status=status,
        filled_quantity=1,
        avg_fill_price=Decimal("1500.00"),
    )
    if status is not OrderStatus.AWAITING_CONFIRMATION:
        setattr(order, "client_request_id", "request-1")
        setattr(order, "confirmed_payload", {"quantity": 100})
        setattr(order, "confirmed_at", datetime.now(UTC))
    if status is OrderStatus.REJECTED:
        setattr(order, "reject_code", "insufficient_cash")
        setattr(order, "reject_message", "余额不足")
        setattr(order, "completed_at", datetime.now(UTC))
    db_session.add(order)

    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("status", [OrderStatus.CANCELLED, OrderStatus.EXPIRED])
def test_unfilled_terminal_state_rejects_fully_filled_quantity(
    db_session: Session, user: User, status: OrderStatus
) -> None:
    account = _account(db_session, user)
    order = _order(
        account=account,
        user=user,
        status=status,
        filled_quantity=100,
        avg_fill_price=Decimal("1500.00"),
        completed_at=datetime.now(UTC),
    )
    setattr(order, "client_request_id", "request-1")
    setattr(order, "confirmed_payload", {"quantity": 100})
    setattr(order, "confirmed_at", datetime.now(UTC))
    db_session.add(order)

    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize(
    ("status", "filled_quantity", "avg_fill_price", "terminal"),
    [
        (OrderStatus.QUEUED, 0, None, False),
        (OrderStatus.OPEN, 0, None, False),
        (OrderStatus.PARTIALLY_FILLED, 1, Decimal("1500.00"), False),
        (OrderStatus.FILLED, 100, Decimal("1500.00"), True),
        (OrderStatus.EXPIRED, 0, None, True),
        (OrderStatus.REJECTED, 0, None, True),
    ],
)
def test_confirmed_state_requires_confirmation_bundle(
    db_session: Session,
    user: User,
    status: OrderStatus,
    filled_quantity: int,
    avg_fill_price: Decimal | None,
    terminal: bool,
) -> None:
    account = _account(db_session, user)
    db_session.add(
        _order(
            account=account,
            user=user,
            status=status,
            filled_quantity=filled_quantity,
            avg_fill_price=avg_fill_price,
            completed_at=datetime.now(UTC) if terminal else None,
            reject_code="rejected" if status is OrderStatus.REJECTED else None,
            reject_message="rejected" if status is OrderStatus.REJECTED else None,
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("missing", ["client_request_id", "confirmed_payload", "confirmed_at"])
def test_confirmation_bundle_is_all_or_nothing(
    db_session: Session, user: User, missing: str
) -> None:
    account = _account(db_session, user)
    order = _order(account=account, user=user, status=OrderStatus.OPEN)
    setattr(order, "client_request_id", "request-1")
    setattr(order, "confirmed_payload", {"quantity": 100})
    setattr(order, "confirmed_at", datetime.now(UTC))
    setattr(order, missing, None)
    db_session.add(order)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_awaiting_confirmation_rejects_confirmation_bundle(db_session: Session, user: User) -> None:
    account = _account(db_session, user)
    order = _order(account=account, user=user)
    setattr(order, "client_request_id", "request-1")
    setattr(order, "confirmed_payload", {"quantity": 100})
    setattr(order, "confirmed_at", datetime.now(UTC))
    db_session.add(order)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_partially_filled_cancellation_requires_confirmation(
    db_session: Session, user: User
) -> None:
    account = _account(db_session, user)
    db_session.add(
        _order(
            account=account,
            user=user,
            status=OrderStatus.CANCELLED,
            filled_quantity=1,
            avg_fill_price=Decimal("1500.00"),
            completed_at=datetime.now(UTC),
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("field", ["limit_price", "avg_fill_price"])
@pytest.mark.parametrize("special", ["NaN", "Infinity", "-Infinity"])
def test_order_rejects_nonfinite_financial_values(
    db_session: Session, user: User, field: str, special: str
) -> None:
    account = _account(db_session, user)
    order = _order(account=account, user=user)
    if field == "avg_fill_price":
        setattr(order, "filled_quantity", 1)
        setattr(order, "status", OrderStatus.PARTIALLY_FILLED)
        setattr(order, "client_request_id", "request-1")
        setattr(order, "confirmed_payload", {"quantity": 100})
        setattr(order, "confirmed_at", datetime.now(UTC))
    setattr(order, field, Decimal(special))
    db_session.add(order)

    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("field", ["expires_at", "confirmed_at", "completed_at"])
def test_order_rejects_naive_client_timestamps(db_session: Session, user: User, field: str) -> None:
    account = _account(db_session, user)
    order = _order(account=account, user=user)
    setattr(order, field, datetime(2026, 7, 18, 9, 30))
    db_session.add(order)

    with pytest.raises(StatementError, match="timezone-aware"):
        db_session.flush()


def test_order_has_global_status_expiry_scan_index() -> None:
    assert any(
        [column.name for column in index.columns] == ["status", "expires_at"]
        for index in PaperOrder.__table__.indexes
    )


@pytest.mark.parametrize("field", ["source_session_id", "source_message_id"])
def test_order_rejects_blank_source_ids(db_session: Session, user: User, field: str) -> None:
    account = _account(db_session, user)
    order = _order(account=account, user=user)
    setattr(order, field, " ")
    db_session.add(order)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_order_rejects_indeterminate_timezone(db_session: Session, user: User) -> None:
    account = _account(db_session, user)
    order = _order(account=account, user=user)
    setattr(
        order,
        "expires_at",
        datetime(2026, 7, 18, 9, 30, tzinfo=_IndeterminateTimezone()),
    )
    db_session.add(order)

    with pytest.raises(StatementError, match="timezone-aware"):
        db_session.flush()


@pytest.mark.parametrize(
    ("status", "filled_quantity", "confirmed", "terminal"),
    [
        (OrderStatus.AWAITING_CONFIRMATION, 0, False, False),
        (OrderStatus.QUEUED, 0, True, False),
        (OrderStatus.OPEN, 0, True, False),
        (OrderStatus.PARTIALLY_FILLED, 1, True, False),
        (OrderStatus.FILLED, 100, True, True),
        (OrderStatus.CANCELLED, 0, False, True),
        (OrderStatus.CANCELLED, 1, True, True),
        (OrderStatus.EXPIRED, 1, True, True),
        (OrderStatus.REJECTED, 0, True, True),
    ],
)
def test_valid_state_shapes_are_persisted(
    db_session: Session,
    user: User,
    status: OrderStatus,
    filled_quantity: int,
    confirmed: bool,
    terminal: bool,
) -> None:
    account = _account(db_session, user)
    order = _order(
        account=account,
        user=user,
        status=status,
        filled_quantity=filled_quantity,
        avg_fill_price=Decimal("1500.00") if filled_quantity else None,
        completed_at=datetime.now(UTC) if terminal else None,
        reject_code="rejected" if status is OrderStatus.REJECTED else None,
        reject_message="rejected" if status is OrderStatus.REJECTED else None,
    )
    if confirmed:
        setattr(order, "client_request_id", "request-1")
        setattr(order, "confirmed_payload", {"quantity": 100})
        setattr(order, "confirmed_at", datetime.now(UTC))
    db_session.add(order)

    db_session.flush()


def test_fill_persists_execution_evidence(db_session: Session, user: User) -> None:
    account = _account(db_session, user)
    order = _order(account=account, user=user)
    db_session.add(order)
    db_session.flush()
    fill = _fill(order)
    db_session.add(fill)
    db_session.flush()

    assert fill.quote_timestamp is not None
    assert fill.quote_source == "fixed-test-quote"
    assert fill.executed_at is not None
    assert fill.trade_id is not None
    assert fill.gross_amount == Decimal("150000.00")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("fill_seq", 0),
        ("quantity", 0),
        ("price", Decimal("0.00")),
        ("gross_amount", Decimal("0.00")),
        ("commission", Decimal("-0.01")),
        ("stamp_duty", Decimal("-0.01")),
        ("transfer_fee", Decimal("-0.01")),
    ],
)
def test_fill_rejects_invalid_amounts(
    db_session: Session, user: User, field: str, value: Decimal | int
) -> None:
    account = _account(db_session, user)
    order = _order(account=account, user=user)
    db_session.add(order)
    db_session.flush()
    fill = _fill(order)
    setattr(fill, field, value)
    db_session.add(fill)

    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize(
    "field", ["price", "gross_amount", "commission", "stamp_duty", "transfer_fee"]
)
@pytest.mark.parametrize("special", ["NaN", "Infinity", "-Infinity"])
def test_fill_rejects_nonfinite_financial_values(
    db_session: Session, user: User, field: str, special: str
) -> None:
    account = _account(db_session, user)
    order = _order(account=account, user=user)
    db_session.add(order)
    db_session.flush()
    fill = _fill(order)
    setattr(fill, field, Decimal(special))
    db_session.add(fill)

    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("field", ["quote_timestamp", "executed_at"])
def test_fill_rejects_naive_execution_timestamps(
    db_session: Session, user: User, field: str
) -> None:
    account = _account(db_session, user)
    order = _order(account=account, user=user)
    db_session.add(order)
    db_session.flush()
    fill = _fill(order)
    setattr(fill, field, datetime(2026, 7, 18, 9, 30))
    db_session.add(fill)

    with pytest.raises(StatementError, match="timezone-aware"):
        db_session.flush()


def test_fill_rejects_blank_quote_source(db_session: Session, user: User) -> None:
    account = _account(db_session, user)
    order = _order(account=account, user=user)
    db_session.add(order)
    db_session.flush()
    fill = _fill(order)
    setattr(fill, "quote_source", " ")
    db_session.add(fill)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_fill_gross_must_equal_quantity_times_price(db_session: Session, user: User) -> None:
    account = _account(db_session, user)
    order = _order(account=account, user=user)
    db_session.add(order)
    db_session.flush()
    fill = _fill(order)
    fill.gross_amount = Decimal("1.00")  # type: ignore[assignment]
    db_session.add(fill)

    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("duplicate", ["sequence", "trade"])
def test_fill_sequence_and_projected_trade_are_unique(
    db_session: Session, user: User, duplicate: str
) -> None:
    account = _account(db_session, user)
    order = _order(account=account, user=user)
    db_session.add(order)
    db_session.flush()
    first = _fill(order)
    db_session.add(first)
    db_session.flush()
    second = _fill(
        order,
        fill_seq=cast(int, first.fill_seq) if duplicate == "sequence" else 2,
        trade_id=cast(uuid.UUID, first.trade_id) if duplicate == "trade" else None,
    )
    db_session.add(second)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_match_pass_persists_consumed_quote_summary(db_session: Session, user: User) -> None:
    account = _account(db_session, user)
    order = _order(account=account, user=user)
    db_session.add(order)
    db_session.flush()
    quote_timestamp = datetime.now(UTC)
    match_pass = PaperMatchPass(
        order_id=order.id,
        quote_timestamp=quote_timestamp,
        match_pass=1,
        quote_source="fixed-test-quote",
        snapshot_summary={"asks": [["1500.00", 100]]},
        consumed_levels=[{"side": "ask", "level": 1, "quantity": 100}],
        matched_quantity=100,
    )
    db_session.add(match_pass)
    db_session.flush()

    assert match_pass.snapshot_summary["asks"][0][0] == "1500.00"
    assert match_pass.consumed_levels[0]["quantity"] == 100
    assert match_pass.created_at is not None


@pytest.mark.parametrize("field", ["snapshot_summary", "consumed_levels"])
def test_match_pass_rejects_none_for_required_snapshots(
    db_session: Session, user: User, field: str
) -> None:
    account = _account(db_session, user)
    order = _order(account=account, user=user)
    db_session.add(order)
    db_session.flush()
    match_pass = PaperMatchPass(
        order_id=order.id,
        quote_timestamp=datetime.now(UTC),
        match_pass=1,
        quote_source="fixed-test-quote",
        snapshot_summary={},
        consumed_levels=[],
        matched_quantity=0,
    )
    setattr(match_pass, field, None)
    db_session.add(match_pass)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_match_pass_watermark_is_unique(db_session: Session, user: User) -> None:
    account = _account(db_session, user)
    order = _order(account=account, user=user)
    db_session.add(order)
    db_session.flush()
    quote_timestamp = datetime.now(UTC)

    def match_pass_row() -> PaperMatchPass:
        return PaperMatchPass(
            order_id=order.id,
            quote_timestamp=quote_timestamp,
            match_pass=1,
            quote_source="fixed-test-quote",
            snapshot_summary={},
            consumed_levels=[],
            matched_quantity=0,
        )

    db_session.add(match_pass_row())
    db_session.flush()
    db_session.add(match_pass_row())

    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize(("match_pass", "matched_quantity"), [(0, 0), (1, -1)])
def test_match_pass_rejects_invalid_counters(
    db_session: Session,
    user: User,
    match_pass: int,
    matched_quantity: int,
) -> None:
    account = _account(db_session, user)
    order = _order(account=account, user=user)
    db_session.add(order)
    db_session.flush()
    db_session.add(
        PaperMatchPass(
            order_id=order.id,
            quote_timestamp=datetime.now(UTC),
            match_pass=match_pass,
            quote_source="fixed-test-quote",
            snapshot_summary={},
            consumed_levels=[],
            matched_quantity=matched_quantity,
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_match_pass_rejects_naive_quote_timestamp(db_session: Session, user: User) -> None:
    account = _account(db_session, user)
    order = _order(account=account, user=user)
    db_session.add(order)
    db_session.flush()
    db_session.add(
        PaperMatchPass(
            order_id=order.id,
            quote_timestamp=datetime(2026, 7, 18, 9, 30),
            match_pass=1,
            quote_source="fixed-test-quote",
            snapshot_summary={},
            consumed_levels=[],
            matched_quantity=0,
        )
    )

    with pytest.raises(StatementError, match="timezone-aware"):
        db_session.flush()


def test_match_pass_rejects_blank_quote_source(db_session: Session, user: User) -> None:
    account = _account(db_session, user)
    order = _order(account=account, user=user)
    db_session.add(order)
    db_session.flush()
    db_session.add(
        PaperMatchPass(
            order_id=order.id,
            quote_timestamp=datetime.now(UTC),
            match_pass=1,
            quote_source=" ",
            snapshot_summary={},
            consumed_levels=[],
            matched_quantity=0,
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_aware_timestamps_round_trip_under_non_utc_connection_timezone(
    db_session: Session, user: User
) -> None:
    db_session.execute(text("SET LOCAL TIME ZONE 'America/New_York'"))
    account = _account(db_session, user)
    order = _order(account=account, user=user)
    expected_instant = cast(datetime, order.expires_at).astimezone(UTC)
    db_session.add(order)
    db_session.flush()
    db_session.expire(order)

    loaded = db_session.get(PaperOrder, order.id)

    assert loaded is not None
    assert loaded.expires_at.utcoffset() is not None
    assert loaded.expires_at.astimezone(UTC) == expected_instant
