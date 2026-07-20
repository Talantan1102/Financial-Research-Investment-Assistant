from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest
from app.models.paper_account import PaperAccount
from app.models.paper_order import (
    OrderSide,
    OrderStatus,
    OrderType,
    PaperFill,
    PaperMatchPass,
    PaperOrder,
)
from app.models.position import Position
from app.models.trade import Trade
from app.models.user import User
from app.services.paper_trading.clock import FixedTradingCalendar
from app.services.paper_trading.errors import PaperTradingError
from app.services.paper_trading.types import QuoteLevel, RealtimeQuote
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

NOW = datetime(2026, 7, 20, 2, 0, tzinfo=UTC)


@pytest.fixture(scope="session")
def paper_trading_worker_fixture_path() -> str:
    return str(Path(__file__).parents[1] / "fixtures" / "paper_trading_worker_quote.json")


def _open_order(session: Session, *, quantity: int = 200) -> PaperOrder:
    token = uuid.uuid4().hex
    user = User(
        username=f"paper-worker-{token}",
        email=f"paper-worker-{token}@example.test",
        hashed_password="x",
    )
    session.add(user)
    session.flush()
    account = PaperAccount.new(
        user_id=cast(uuid.UUID, user.id), generation=1, initial_cash=Decimal("100000.00")
    )
    session.add(account)
    session.flush()
    reserve = (Decimal(quantity) * Decimal("10.01") + Decimal("10.00")).quantize(Decimal("0.01"))
    account.available_cash = Decimal("100000.00") - reserve
    account.frozen_cash = reserve
    order = PaperOrder(
        account_id=account.id,
        account_generation=1,
        user_id=user.id,
        client_request_id=f"confirm-{token}",
        source_session_id="worker-session",
        source_message_id="worker-message",
        proposal_fingerprint=uuid.uuid4().hex * 2,
        ts_code="600519.SH",
        name="贵州茅台",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=quantity,
        limit_price=Decimal("10.01"),
        filled_quantity=0,
        avg_fill_price=None,
        reserved_cash=reserve,
        reserved_quantity=0,
        status=OrderStatus.OPEN,
        original_proposal={"quantity": quantity},
        confirmed_payload={"quantity": quantity},
        user_edits=None,
        quote_snapshot={
            "source": "confirmed",
            "daily_lower_bound": "9.00",
            "daily_upper_bound": "11.00",
            "price_tick": "0.01",
        },
        rules_version="cn-a-20260706",
        expires_at=NOW + timedelta(hours=1),
        confirmed_at=NOW,
        completed_at=None,
    )
    session.add(order)
    session.flush()
    return order


def _quote(*, asks: tuple[QuoteLevel, ...], at: datetime = NOW) -> RealtimeQuote:
    last_ask = asks[-1].price if asks else Decimal("10.01")
    empty_asks = asks + tuple(
        QuoteLevel(price=last_ask + Decimal(index) / 100, quantity=0)
        for index in range(1, 6 - len(asks))
    )
    bids = tuple(
        QuoteLevel(
            price=Decimal("10.00") - Decimal(index) / 100, quantity=1000 if index == 1 else 0
        )
        for index in range(1, 6)
    )
    return RealtimeQuote(
        ts_code="600519.SH",
        name="贵州茅台",
        quoted_at=at,
        previous_close=Decimal("10.00"),
        last_price=Decimal("10.00"),
        bids=bids,
        asks=empty_asks,
        source="fixed-worker",
        suspended=False,
    )


class _Provider:
    def __init__(self, quote: RealtimeQuote) -> None:
        self.quote = quote
        self.calls = 0

    def get_sync(self, ts_code: str) -> RealtimeQuote:
        assert ts_code == "600519.SH"
        self.calls += 1
        return self.quote


def _wire_market(monkeypatch: pytest.MonkeyPatch, quote: RealtimeQuote) -> _Provider:
    import app.tasks.paper_trading as tasks

    provider = _Provider(quote)
    calendar = FixedTradingCalendar({date(2026, 7, 20), date(2026, 7, 21)})
    monkeypatch.setattr(tasks, "_now", lambda: NOW)
    monkeypatch.setattr(tasks, "_calendar", lambda: calendar)
    monkeypatch.setattr(tasks, "TushareRealtimeQuoteProvider", lambda: provider)
    return provider


def test_multilevel_snapshot_settles_in_global_watermark_order(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.tasks.paper_trading as tasks

    order = _open_order(db_session)
    quote = _quote(
        asks=(
            QuoteLevel(price=Decimal("10.00"), quantity=100),
            QuoteLevel(price=Decimal("10.01"), quantity=100),
        )
    )
    provider = _wire_market(monkeypatch, quote)

    first = tasks._match_order_in_session(
        db_session,
        order_id=str(order.id),
        quote_timestamp=NOW.isoformat(),
        match_pass=1,
    )
    second = tasks._match_order_in_session(
        db_session,
        order_id=str(order.id),
        quote_timestamp=NOW.isoformat(),
        match_pass=1,
    )
    replay_with_different_pass = tasks._match_order_in_session(
        db_session,
        order_id=str(order.id),
        quote_timestamp=NOW.isoformat(),
        match_pass=2,
    )

    assert first == second == replay_with_different_pass
    assert first["matched_quantity"] == 200
    assert len(cast(list[str], first["fill_ids"])) == 2
    assert provider.calls == 1
    assert [
        row.match_pass
        for row in db_session.scalars(select(PaperMatchPass).order_by(PaperMatchPass.match_pass))
    ] == [1, 2]
    assert db_session.query(PaperFill).count() == 2
    assert order.status is OrderStatus.FILLED


def test_no_visible_depth_persists_one_empty_watermark_without_fill(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.tasks.paper_trading as tasks

    order = _open_order(db_session, quantity=100)
    provider = _wire_market(
        monkeypatch,
        _quote(asks=(QuoteLevel(price=Decimal("10.02"), quantity=100),)),
    )

    first = tasks._match_order_in_session(
        db_session,
        order_id=str(order.id),
        quote_timestamp=NOW.isoformat(),
        match_pass=1,
    )
    second = tasks._match_order_in_session(
        db_session,
        order_id=str(order.id),
        quote_timestamp=NOW.isoformat(),
        match_pass=1,
    )

    assert first == second
    assert first["fill_ids"] == []
    assert provider.calls == 1
    assert db_session.query(PaperFill).count() == 0
    watermark = db_session.query(PaperMatchPass).one()
    assert watermark.matched_quantity == 0 and watermark.fill_id is None


def test_snapshot_replay_never_includes_a_later_snapshot(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.tasks.paper_trading as tasks

    order = _open_order(db_session, quantity=200)
    _wire_market(monkeypatch, _quote(asks=(QuoteLevel(price=Decimal("10.00"), quantity=100),)))
    first = tasks._match_order_in_session(
        db_session, order_id=str(order.id), quote_timestamp=NOW.isoformat(), match_pass=1
    )
    later_time = NOW + timedelta(seconds=1)
    _wire_market(
        monkeypatch,
        _quote(asks=(QuoteLevel(price=Decimal("10.00"), quantity=100),), at=later_time),
    )
    later = tasks._match_order_in_session(
        db_session, order_id=str(order.id), quote_timestamp=later_time.isoformat(), match_pass=2
    )
    replay = tasks._match_order_in_session(
        db_session, order_id=str(order.id), quote_timestamp=NOW.isoformat(), match_pass=2
    )

    assert replay == first
    assert replay["fill_ids"] != later["fill_ids"]
    assert len(cast(list[str], replay["fill_ids"])) == 1


def test_concurrent_same_snapshot_is_consumed_once(
    pg_test_engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.tasks.paper_trading as tasks

    factory = sessionmaker(bind=pg_test_engine, expire_on_commit=False)
    with factory() as session:
        order = _open_order(session, quantity=100)
        session.commit()
        order_id = str(order.id)
    _wire_market(monkeypatch, _quote(asks=(QuoteLevel(price=Decimal("10.00"), quantity=100),)))

    def run(match_pass: int) -> tuple[str, object]:
        with factory() as session:
            try:
                result = tasks._match_order_in_session(
                    session,
                    order_id=order_id,
                    quote_timestamp=NOW.isoformat(),
                    match_pass=match_pass,
                )
                session.commit()
                return "ok", result
            except PaperTradingError as exc:
                session.rollback()
                return "error", exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(run, (1, 2)))

    assert any(kind == "ok" for kind, _ in outcomes)
    assert all(value == "match_pass_conflict" for kind, value in outcomes if kind == "error")
    with factory() as session:
        assert session.query(PaperFill).filter_by(order_id=uuid.UUID(order_id)).count() == 1
        assert session.query(PaperMatchPass).filter_by(order_id=uuid.UUID(order_id)).count() == 1


def test_stale_quote_rolls_back_without_fill(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.tasks.paper_trading as tasks

    order = _open_order(db_session, quantity=100)
    _wire_market(
        monkeypatch,
        _quote(
            asks=(QuoteLevel(price=Decimal("10.00"), quantity=100),),
            at=NOW - timedelta(seconds=16),
        ),
    )

    with pytest.raises(PaperTradingError) as stale:
        tasks._match_order_in_session(
            db_session,
            order_id=str(order.id),
            quote_timestamp=None,
            match_pass=None,
        )

    assert stale.value.code == "stale_quote"
    assert db_session.query(PaperFill).count() == 0
    assert db_session.query(PaperMatchPass).count() == 0


def test_expired_order_is_released_without_fetching_quote(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.tasks.paper_trading as tasks

    order = _open_order(db_session, quantity=100)
    order.expires_at = NOW - timedelta(seconds=1)
    provider = _wire_market(
        monkeypatch, _quote(asks=(QuoteLevel(price=Decimal("10.00"), quantity=100),))
    )

    result = tasks._match_order_in_session(
        db_session, order_id=str(order.id), quote_timestamp=None, match_pass=None
    )

    assert result == {"fill_ids": [], "matched_quantity": 0}
    assert provider.calls == 0
    assert order.status is OrderStatus.EXPIRED
    assert order.reserved_cash == Decimal("0.00")


def test_provider_failure_leaves_order_and_watermark_unchanged(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.tasks.paper_trading as tasks

    order = _open_order(db_session, quantity=100)
    calendar = FixedTradingCalendar({date(2026, 7, 20), date(2026, 7, 21)})

    class _BrokenProvider:
        def get_sync(self, _ts_code: str) -> RealtimeQuote:
            raise PaperTradingError("quote_unavailable", "feed unavailable")

    monkeypatch.setattr(tasks, "_now", lambda: NOW)
    monkeypatch.setattr(tasks, "_calendar", lambda: calendar)
    monkeypatch.setattr(tasks, "TushareRealtimeQuoteProvider", _BrokenProvider)

    with pytest.raises(PaperTradingError) as unavailable:
        tasks._match_order_in_session(
            db_session, order_id=str(order.id), quote_timestamp=None, match_pass=None
        )

    assert unavailable.value.code == "quote_unavailable"
    assert order.status is OrderStatus.OPEN
    assert db_session.query(PaperFill).count() == 0
    assert db_session.query(PaperMatchPass).count() == 0


def test_release_t1_lots_checks_real_calendar_and_is_idempotent(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.tasks.paper_trading as tasks

    order = _open_order(db_session, quantity=100)
    _wire_market(monkeypatch, _quote(asks=(QuoteLevel(price=Decimal("10.00"), quantity=100),)))
    tasks._match_order_in_session(
        db_session,
        order_id=str(order.id),
        quote_timestamp=NOW.isoformat(),
        match_pass=1,
    )
    release_time = datetime(2026, 7, 21, 1, 20, tzinfo=UTC)
    monkeypatch.setattr(tasks, "_now", lambda: release_time)
    monkeypatch.setattr(
        tasks,
        "_calendar",
        lambda: FixedTradingCalendar({date(2026, 7, 20), date(2026, 7, 21)}),
    )

    assert tasks._release_t1_lots_in_session(db_session) == 1
    assert tasks._release_t1_lots_in_session(db_session) == 1

    monkeypatch.setattr(tasks, "_calendar", lambda: FixedTradingCalendar({date(2026, 7, 20)}))
    assert tasks._release_t1_lots_in_session(db_session) == 0


@pytest.mark.e2e
def test_worker_redelivery_returns_existing_fill_without_duplicate(
    pg_test_engine, redis_url: str, celery_worker_subprocess: None
) -> None:
    """A real worker performs first settlement, then replays the same snapshot."""
    del redis_url, celery_worker_subprocess
    factory = sessionmaker(bind=pg_test_engine, expire_on_commit=False)
    with factory() as session:
        order = _open_order(session, quantity=100)
        session.commit()
        order_id = str(order.id)

    from app.tasks.paper_trading import match_order

    first = match_order.delay(order_id).get(timeout=30)
    second = match_order.delay(
        order_id,
        cast(str, first["quote_timestamp"]),
        cast(int, first["match_pass"]),
    ).get(timeout=30)

    assert first["fill_ids"] == second["fill_ids"]
    with factory() as session:
        order = session.get(PaperOrder, uuid.UUID(order_id))
        account = session.get(PaperAccount, order.account_id)
        assert order.status is OrderStatus.FILLED
        assert order.filled_quantity == 100
        assert account.frozen_cash == Decimal("0.00")
        assert account.available_cash == Decimal("98994.99")
        assert session.query(PaperFill).filter_by(order_id=uuid.UUID(order_id)).count() == 1
        assert session.query(PaperMatchPass).filter_by(order_id=uuid.UUID(order_id)).count() == 1
        assert session.query(Trade).filter_by(paper_account_id=account.id).count() == 1
        assert session.query(Position).filter_by(paper_account_id=account.id).one().quantity == 100
