"""Celery entrypoints for simulated-order matching and market-clock maintenance."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, time
from decimal import Decimal
from typing import cast
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.paper_account import PaperAccount, PaperAccountStatus, PaperHoldingLot
from app.models.paper_order import OrderSide, OrderStatus, OrderType, PaperMatchPass, PaperOrder
from app.services.paper_trading.clock import TradingClock, TushareTradingCalendar
from app.services.paper_trading.errors import PaperTradingError
from app.services.paper_trading.matcher import Execution, match_visible_depth
from app.services.paper_trading.order_service import PaperOrderService
from app.services.paper_trading.quote_provider import (
    TushareRealtimeQuoteProvider,
    assert_fresh_quote,
)
from app.services.paper_trading.rulebook import RuleBook
from app.services.paper_trading.settlement import MatchQuoteEvidence, PaperSettlementService
from app.services.paper_trading.types import MarketPhase
from app.services.tushare_factory import build_tushare_service
from app.tasks.celery_app import celery_app

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _now() -> datetime:
    return datetime.now(UTC)


def _fetch_trading_calendar(start: str, end: str) -> pd.DataFrame:
    async def fetch() -> pd.DataFrame:
        service = build_tushare_service()
        try:
            return await service.get_trade_cal(start=start, end=end)
        finally:
            await service.aclose()

    return asyncio.run(fetch())


def _calendar() -> TushareTradingCalendar:
    return TushareTradingCalendar(_fetch_trading_calendar)


def _order_service(session: Session, *, now: Callable[[], datetime]) -> PaperOrderService:
    return PaperOrderService(
        session,
        quote_provider=TushareRealtimeQuoteProvider(),
        clock=TradingClock(_calendar()),
        rulebook=RuleBook.from_builtin_fixture(),
        now=now,
    )


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (AttributeError, TypeError, ValueError) as exc:
        raise PaperTradingError("invalid_order_id", "order_id must be a UUID") from exc


def _parse_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise PaperTradingError("invalid_quote_timestamp", "quote timestamp is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PaperTradingError("invalid_quote_timestamp", "quote timestamp must be timezone-aware")
    return parsed


def _existing_result(
    session: Session, *, order_id: uuid.UUID, quote_timestamp: datetime, match_pass: int | None
) -> dict[str, object] | None:
    statement = select(PaperMatchPass).where(
        PaperMatchPass.order_id == order_id,
        PaperMatchPass.quote_timestamp == quote_timestamp,
    )
    if match_pass is not None:
        statement = statement.where(PaperMatchPass.match_pass >= match_pass)
    rows = session.scalars(statement.order_by(PaperMatchPass.match_pass)).all()
    if not rows or (match_pass is not None and int(rows[0].match_pass) != match_pass):
        return None
    return {
        "fill_ids": [str(row.fill_id) for row in rows if row.fill_id is not None],
        "matched_quantity": sum(int(row.matched_quantity) for row in rows),
        "quote_timestamp": quote_timestamp.isoformat(),
        "match_pass": int(rows[0].match_pass),
    }


def _match_order_in_session(
    session: Session,
    *,
    order_id: str,
    quote_timestamp: str | None,
    match_pass: int | None,
) -> dict[str, object]:
    parsed_id = _parse_uuid(order_id)
    parsed_timestamp = _parse_timestamp(quote_timestamp)
    if match_pass is not None and (
        isinstance(match_pass, bool) or not isinstance(match_pass, int) or match_pass <= 0
    ):
        raise PaperTradingError("invalid_match_pass", "match_pass must be positive")
    if parsed_timestamp is not None and match_pass is not None:
        existing = _existing_result(
            session,
            order_id=parsed_id,
            quote_timestamp=parsed_timestamp,
            match_pass=match_pass,
        )
        if existing is not None:
            return existing

    order = session.scalar(select(PaperOrder).where(PaperOrder.id == parsed_id))
    if order is None:
        raise PaperTradingError("order_not_found", "paper order does not exist")
    now = _now()
    if order.status not in {OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED}:
        return {"fill_ids": [], "matched_quantity": 0}
    if order.expires_at <= now:
        _order_service(session, now=lambda: now).expire_open_orders(at=now)
        return {"fill_ids": [], "matched_quantity": 0}

    calendar = _calendar()
    clock = TradingClock(calendar)
    if clock.phase(now) not in {MarketPhase.MORNING, MarketPhase.AFTERNOON}:
        return {"fill_ids": [], "matched_quantity": 0}

    quote = TushareRealtimeQuoteProvider().get_sync(cast(str, order.ts_code))
    if parsed_timestamp is not None and quote.quoted_at != parsed_timestamp:
        raise PaperTradingError("quote_timestamp_mismatch", "quote timestamp changed")
    timestamp = parsed_timestamp or quote.quoted_at
    # Network I/O happened before the lock. Serialize only the DB phase so two
    # workers cannot allocate the same next global watermark for different snapshots.
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"paper-match:{parsed_id}"},
    )
    existing = _existing_result(
        session, order_id=parsed_id, quote_timestamp=timestamp, match_pass=match_pass
    )
    if existing is not None:
        return existing
    session.refresh(order)
    if order.status not in {OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED}:
        return {"fill_ids": [], "matched_quantity": 0}
    rules = RuleBook.from_builtin_fixture().resolve(
        ts_code=cast(str, order.ts_code),
        board=_board(cast(str, order.ts_code)),
        risk_warning=cast(str, order.name).upper().startswith(("ST", "*ST")),
        side=order.side.value,
        on=now.astimezone(SHANGHAI).date(),
    )
    assert_fresh_quote(quote, now, rules.quote_freshness_seconds)
    source = quote.source.strip()
    if not source or len(source) > 64:
        raise PaperTradingError("invalid_match_evidence", "quote source is invalid")
    if source != quote.source:
        quote = quote.model_copy(update={"source": source})
    remaining = int(order.quantity) - int(order.filled_quantity)
    executions = tuple(
        match_visible_depth(
            side=cast(OrderSide, order.side),
            order_type=cast(OrderType, order.order_type),
            remaining=remaining,
            limit_price=cast(Decimal | None, order.limit_price),
            quote=quote,
        )
    )
    next_pass = session.scalar(
        select(func.coalesce(func.max(PaperMatchPass.match_pass), 0)).where(
            PaperMatchPass.order_id == parsed_id
        )
    )
    expected_pass = int(next_pass or 0) + 1
    base_pass = match_pass or expected_pass
    if base_pass != expected_pass:
        raise PaperTradingError("match_pass_conflict", "match-pass watermark is not next")
    if not executions:
        session.add(
            PaperMatchPass(
                order_id=parsed_id,
                quote_timestamp=timestamp,
                match_pass=base_pass,
                quote_source=quote.source,
                snapshot_summary=quote.model_dump(mode="json"),
                consumed_levels=[],
                matched_quantity=0,
            )
        )
        session.flush()
        return {
            "fill_ids": [],
            "matched_quantity": 0,
            "quote_timestamp": timestamp.isoformat(),
            "match_pass": base_pass,
        }

    def evidence_provider(**kwargs: object) -> MatchQuoteEvidence:
        execution = kwargs["execution"]
        assert isinstance(execution, Execution)
        return MatchQuoteEvidence(
            quote=quote,
            consumed_levels=executions,
            execution_index=executions.index(execution),
            remaining_before_match=remaining,
        )

    settlement = PaperSettlementService(
        session,
        calendar=calendar,
        now=lambda: now,
        evidence_provider=evidence_provider,
    )
    fills = [
        settlement.apply(
            order_id=parsed_id,
            execution=execution,
            quote_timestamp=timestamp,
            match_pass=base_pass + index,
        )
        for index, execution in enumerate(executions)
    ]
    return {
        "fill_ids": [str(fill.id) for fill in fills],
        "matched_quantity": sum(int(fill.quantity) for fill in fills),
        "quote_timestamp": timestamp.isoformat(),
        "match_pass": base_pass,
    }


def _open_queued_orders_in_session(session: Session) -> int:
    now = _now()
    return _order_service(session, now=lambda: now).open_queued_orders(at=now)


def _expire_day_orders_in_session(session: Session) -> int:
    now = _now()
    local = now.astimezone(SHANGHAI)
    calendar = _calendar()
    if not calendar.is_open_date(local.date()) or local.time().replace(tzinfo=None) < time(15, 1):
        return 0
    return _order_service(session, now=lambda: now).expire_open_orders(at=now)


def _release_t1_lots_in_session(session: Session) -> int:
    """Observe matured lots under account locks; sellability is derived from available_on."""
    now = _now()
    local = now.astimezone(SHANGHAI)
    calendar = _calendar()
    if not calendar.is_open_date(local.date()) or local.time().replace(tzinfo=None) < time(9, 20):
        return 0
    accounts = (
        session.scalars(
            select(PaperAccount)
            .join(PaperHoldingLot, PaperHoldingLot.account_id == PaperAccount.id)
            .where(
                PaperAccount.status == PaperAccountStatus.ACTIVE,
                PaperHoldingLot.available_on == local.date(),
                PaperHoldingLot.remaining_quantity > 0,
            )
            .with_for_update(of=PaperAccount, skip_locked=True)
        )
        .unique()
        .all()
    )
    account_ids = [account.id for account in accounts]
    if not account_ids:
        return 0
    return int(
        session.scalar(
            select(func.count(PaperHoldingLot.id)).where(
                PaperHoldingLot.account_id.in_(account_ids),
                PaperHoldingLot.available_on == local.date(),
                PaperHoldingLot.remaining_quantity > 0,
            )
        )
        or 0
    )


def _run_transaction(runner: Callable[[Session], object]) -> object:
    session = SessionLocal()
    try:
        result = runner(session)
        session.commit()
        return result
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@celery_app.task(name="app.tasks.paper_trading.match_order", acks_late=True)
def match_order(
    order_id: str, quote_timestamp: str | None = None, match_pass: int | None = None
) -> dict[str, object]:
    return cast(
        dict[str, object],
        _run_transaction(
            lambda session: _match_order_in_session(
                session,
                order_id=order_id,
                quote_timestamp=quote_timestamp,
                match_pass=match_pass,
            )
        ),
    )


@celery_app.task(name="app.tasks.paper_trading.open_queued_orders")
def open_queued_orders() -> int:
    return cast(int, _run_transaction(_open_queued_orders_in_session))


@celery_app.task(name="app.tasks.paper_trading.expire_day_orders")
def expire_day_orders() -> int:
    return cast(int, _run_transaction(_expire_day_orders_in_session))


@celery_app.task(name="app.tasks.paper_trading.release_t1_lots")
def release_t1_lots() -> int:
    return cast(int, _run_transaction(_release_t1_lots_in_session))


def _board(ts_code: str) -> str:
    code = ts_code.split(".", 1)[0]
    if code.startswith(("300", "301")):
        return "chinext"
    if code.startswith("688"):
        return "star"
    if code.startswith(("8", "4")):
        return "beijing"
    return "main"
