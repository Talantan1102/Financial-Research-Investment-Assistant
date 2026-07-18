from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


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
    reject_code: str | None = None,
    reject_message: str | None = None,
) -> PaperOrder:
    now = datetime.now(UTC)
    return PaperOrder(
        account_id=account.id,
        account_generation=account.generation,
        user_id=user.id,
        client_request_id=client_request_id,
        source_session_id="session-1",
        source_message_id="message-1",
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
        confirmed_payload=None,
        user_edits=None,
        quote_snapshot={"latest_price": "1499.00", "timestamp": now.isoformat()},
        rules_version="cn-a-20260706",
        reject_code=reject_code,
        reject_message=reject_message,
        expires_at=now + timedelta(minutes=5),
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


def test_prepare_allows_multiple_null_confirmation_keys(db_session: Session, user: User) -> None:
    account = _account(db_session, user)
    db_session.add_all([_order(account=account, user=user), _order(account=account, user=user)])

    db_session.flush()


def test_confirmation_key_is_unique_per_user_when_nonnull(db_session: Session, user: User) -> None:
    account = _account(db_session, user)
    db_session.add(_order(account=account, user=user, client_request_id="request-1"))
    db_session.flush()
    db_session.add(_order(account=account, user=user, client_request_id="request-1"))

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
    db_session.add_all(
        [
            _order(account=first_account, user=user, client_request_id="request-1"),
            _order(account=other_account, user=other, client_request_id="request-1"),
        ]
    )

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
            status=OrderStatus.REJECTED,
            reject_code=None,
            reject_message=None,
            completed_at=None,
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
    db_session.add(_order(account=account, user=user, status=OrderStatus.FILLED))

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
            status=status,
            filled_quantity=filled_quantity,
            avg_fill_price=avg_fill_price,
            completed_at=completed_at,
        )
    )

    with pytest.raises(IntegrityError):
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
        fill_seq=first.fill_seq if duplicate == "sequence" else 2,
        trade_id=first.trade_id if duplicate == "trade" else None,
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
