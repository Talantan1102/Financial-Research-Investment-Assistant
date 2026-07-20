"""Celery entrypoints for simulated-order matching and market-clock maintenance."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, time
from decimal import Decimal
from typing import cast
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.paper_account import PaperAccount, PaperAccountStatus, PaperHoldingLot
from app.models.paper_order import OrderSide, OrderStatus, OrderType, PaperMatchPass, PaperOrder
from app.services.paper_trading.clock import (
    TradingCalendar,
    TradingClock,
    TushareTradingCalendar,
)
from app.services.paper_trading.errors import PaperTradingError
from app.services.paper_trading.matcher import Execution, match_visible_depth
from app.services.paper_trading.observability import (
    emit_paper_order_span,
    emit_paper_system_span,
    record_dispatch_failure_state,
    record_dispatch_recovery_if_pending,
)
from app.services.paper_trading.order_service import PaperOrderService
from app.services.paper_trading.quote_provider import (
    TushareRealtimeQuoteProvider,
    assert_fresh_quote,
)
from app.services.paper_trading.reconciliation import reconcile_account
from app.services.paper_trading.rulebook import RuleBook
from app.services.paper_trading.settlement import MatchQuoteEvidence, PaperSettlementService
from app.services.paper_trading.types import MarketPhase
from app.services.trace_models import Span
from app.services.tushare_factory import build_tushare_service
from app.tasks.celery_app import celery_app

SHANGHAI = ZoneInfo("Asia/Shanghai")
logger = logging.getLogger(__name__)


def _record_order_span(
    *,
    order_id: uuid.UUID,
    name: str,
    started_at: datetime,
    attrs: dict[str, object],
    error: str | None = None,
    parent_id: str | None = None,
    span_id: str | None = None,
) -> Span:
    return emit_paper_order_span(
        order_id=order_id,
        name=name,
        started_at=started_at,
        attrs=attrs,
        error=error,
        parent_id=parent_id,
        span_id=span_id,
    )


def _record_system_span(
    *,
    name: str,
    started_at: datetime,
    attrs: dict[str, object],
    error: str | None = None,
) -> Span:
    return emit_paper_system_span(
        name=name,
        started_at=started_at,
        attrs=attrs,
        error=error,
    )


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


def _calendar() -> TradingCalendar:
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
    rows = session.scalars(
        select(PaperMatchPass)
        .where(
            PaperMatchPass.order_id == order_id,
            PaperMatchPass.quote_timestamp == quote_timestamp,
        )
        .order_by(PaperMatchPass.match_pass)
    ).all()
    if not rows:
        return None
    return {
        "fill_ids": [str(row.fill_id) for row in rows if row.fill_id is not None],
        "matched_quantity": sum(int(row.matched_quantity) for row in rows),
        "quote_timestamp": quote_timestamp.isoformat(),
        "match_pass": int(rows[0].match_pass),
        "idempotent_replay": True,
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


def _open_queued_orders_in_session(session: Session) -> tuple[int, list[str]]:
    now = _now()
    service = _order_service(session, now=lambda: now)
    if service.clock.phase(now) not in {MarketPhase.MORNING, MarketPhase.AFTERNOON}:
        return 0, []
    opened = service.open_queued_orders(at=now)
    order_ids = session.scalars(
        select(PaperOrder.id)
        .join(
            PaperAccount,
            (PaperAccount.id == PaperOrder.account_id)
            & (PaperAccount.generation == PaperOrder.account_generation),
        )
        .where(
            PaperOrder.status.in_([OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED]),
            PaperOrder.expires_at > now,
            PaperAccount.status == PaperAccountStatus.ACTIVE,
        )
        .order_by(PaperOrder.id)
    ).all()
    return opened, [str(order_id) for order_id in order_ids]


def _expire_day_orders_in_session(session: Session) -> int:
    now = _now()
    # expires_at is authoritative: compensate for a missed 15:01 run on any
    # later invocation, including weekends, without a remote calendar fetch.
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


def _reconcile_active_accounts() -> dict[str, int]:
    """Reconcile active generations independently so one failure cannot abort the scan."""
    discovery = SessionLocal()
    try:
        account_ids = list(
            discovery.scalars(
                select(PaperAccount.id)
                .where(PaperAccount.status == PaperAccountStatus.ACTIVE)
                .order_by(PaperAccount.id)
            ).all()
        )
    finally:
        discovery.close()

    checked = suspended = errors = 0
    for account_id in account_ids:
        started_at = datetime.now(UTC)
        session = SessionLocal()
        try:
            still_active = session.scalar(
                select(PaperAccount.id).where(
                    PaperAccount.id == account_id,
                    PaperAccount.status == PaperAccountStatus.ACTIVE,
                )
            )
            if still_active is None:
                continue
            violations = reconcile_account(session, account_id, require_active=True)
            if violations is None:
                session.rollback()
                continue
            session.commit()
            checked += 1
            suspended += int(bool(violations))
            _record_system_span(
                name="reconcile",
                started_at=started_at,
                attrs={
                    "outcome": "violation" if violations else "success",
                    "reconciliation_errors": 0,
                    "violation_count": len(violations),
                },
            )
        except Exception:
            session.rollback()
            errors += 1
            logger.exception(
                "paper account reconciliation failed",
                extra={"account_id": str(account_id)},
            )
            _record_system_span(
                name="reconcile",
                started_at=started_at,
                attrs={
                    "outcome": "failure",
                    "reconciliation_errors": 1,
                    "violation_count": 0,
                },
                error="reconciliation_error",
            )
        finally:
            session.close()
    return {"checked": checked, "suspended": suspended, "errors": errors}


def dispatch_match_order(
    order_id: uuid.UUID | str,
    *,
    trace_parent_id: str | None = None,
    recovery: bool = False,
) -> bool:
    """Best-effort dispatch; the periodic open-order scan is the recovery path."""
    started_at = datetime.now(UTC)
    parsed_id = _parse_uuid(str(order_id))
    dispatch_span_id = f"paper-{parsed_id}-dispatch-{uuid.uuid4().hex[:8]}"
    try:
        match_order.apply_async(
            args=[str(order_id)],
            kwargs={"trace_parent_id": dispatch_span_id},
            retry=False,
        )
    except Exception:
        logger.exception(
            "paper match dispatch failed; periodic scan will retry",
            extra={"order_id": str(order_id)},
        )
        _record_order_span(
            order_id=parsed_id,
            name="dispatch",
            started_at=started_at,
            attrs={"dispatch_failed": True, "outcome": "failure"},
            error="dispatch_failed",
            parent_id=trace_parent_id,
            span_id=dispatch_span_id,
        )
        record_dispatch_failure_state(order_id=parsed_id, session_factory=SessionLocal)
        return False
    if recovery:
        record_dispatch_recovery_if_pending(
            order_id=parsed_id,
            started_at=started_at,
            parent_id=dispatch_span_id,
            session_factory=SessionLocal,
        )
    _record_order_span(
        order_id=parsed_id,
        name="dispatch",
        started_at=started_at,
        attrs={
            "dispatch_failed": False,
            "outcome": "scan_dispatched" if recovery else "success",
        },
        parent_id=trace_parent_id,
        span_id=dispatch_span_id,
    )
    return True


@celery_app.task(name="app.tasks.paper_trading.match_order", acks_late=True)
def match_order(
    order_id: str,
    quote_timestamp: str | None = None,
    match_pass: int | None = None,
    trace_parent_id: str | None = None,
) -> dict[str, object]:
    parsed_id = _parse_uuid(order_id)
    started_at = datetime.now(UTC)
    try:
        result = cast(
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
    except Exception as exc:
        error_code = exc.code if isinstance(exc, PaperTradingError) else "internal_error"
        _record_order_span(
            order_id=parsed_id,
            name="match",
            started_at=started_at,
            attrs={"outcome": "failure", "error_code": error_code},
            error=error_code,
            parent_id=trace_parent_id,
        )
        raise
    replay = result.get("idempotent_replay") is True
    raw_matched_quantity = result.get("matched_quantity", 0)
    matched_quantity = (
        raw_matched_quantity
        if isinstance(raw_matched_quantity, int) and not isinstance(raw_matched_quantity, bool)
        else 0
    )
    fill_ids = result.get("fill_ids")
    fill_count = len(fill_ids) if isinstance(fill_ids, list) else 0
    outcome = (
        "idempotent_replay"
        if replay
        else (
            "filled"
            if matched_quantity
            else ("empty_book" if "quote_timestamp" in result else "noop")
        )
    )
    match_span = _record_order_span(
        order_id=parsed_id,
        name="match",
        started_at=started_at,
        attrs={
            "fill_count": fill_count,
            "idempotent_replay": replay,
            "matched_quantity": matched_quantity,
            "outcome": outcome,
        },
        parent_id=trace_parent_id,
    )
    if matched_quantity > 0 and not replay:
        _record_order_span(
            order_id=parsed_id,
            name="settle",
            started_at=started_at,
            attrs={
                "fill_count": fill_count,
                "matched_quantity": matched_quantity,
                "outcome": "success",
            },
            parent_id=getattr(match_span, "span_id", trace_parent_id),
        )
    return result


@celery_app.task(name="app.tasks.paper_trading.open_queued_orders")
def open_queued_orders() -> int:
    opened, order_ids = cast(
        tuple[int, list[str]], _run_transaction(_open_queued_orders_in_session)
    )
    for order_id in order_ids:
        dispatch_match_order(order_id, recovery=True)
    return opened


@celery_app.task(
    name="app.tasks.paper_trading.expire_day_orders",
    autoretry_for=(OperationalError, OSError),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def expire_day_orders() -> int:
    return cast(int, _run_transaction(_expire_day_orders_in_session))


@celery_app.task(name="app.tasks.paper_trading.release_t1_lots")
def release_t1_lots() -> int:
    return cast(int, _run_transaction(_release_t1_lots_in_session))


@celery_app.task(name="app.tasks.paper_trading.reconcile_paper_accounts")
def reconcile_paper_accounts() -> dict[str, int]:
    return _reconcile_active_accounts()


def _board(ts_code: str) -> str:
    code = ts_code.split(".", 1)[0]
    if code.startswith(("300", "301")):
        return "chinext"
    if code.startswith("688"):
        return "star"
    if code.startswith(("8", "4")):
        return "beijing"
    return "main"
