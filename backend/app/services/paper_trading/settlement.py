from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import cast
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.paper_account import (
    PaperAccount,
    PaperAccountStatus,
    PaperHoldingLot,
)
from app.models.paper_order import (
    OrderSide,
    OrderStatus,
    OrderType,
    PaperFill,
    PaperLotReservation,
    PaperMatchPass,
    PaperOrder,
)
from app.models.position import Position
from app.models.trade import TradeType
from app.services.paper_trading.account_service import PaperAccountService
from app.services.paper_trading.clock import TradingCalendar
from app.services.paper_trading.errors import PaperTradingError
from app.services.paper_trading.fee_schedule import FeeSchedule
from app.services.paper_trading.matcher import Execution, match_visible_depth
from app.services.paper_trading.types import FeeBreakdown, RealtimeQuote
from app.services.trade_service import TradeService

SHANGHAI = ZoneInfo("Asia/Shanghai")
_CENT = Decimal("0.01")
_FOUR_PLACES = Decimal("0.0001")


class MatchQuoteEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)

    quote: RealtimeQuote
    consumed_levels: tuple[Execution, ...]
    execution_index: int = Field(
        ge=0, description="Zero-based position in the matcher result for this quote snapshot"
    )
    remaining_before_match: int = Field(
        gt=0, description="Order quantity remaining before this quote snapshot was matched"
    )


class PaperSettlementService:
    """Apply one execution and all of its projections in the caller transaction."""

    def __init__(
        self,
        session: Session,
        *,
        calendar: TradingCalendar,
        now: Callable[[], datetime],
        fee_schedule: FeeSchedule | None = None,
        trade_service: TradeService | None = None,
        evidence_provider: Callable[..., MatchQuoteEvidence],
    ) -> None:
        self._session = session
        self._calendar = calendar
        self._now = now
        self._fees = fee_schedule or FeeSchedule.from_builtin_fixture()
        self._accounts = PaperAccountService(session)
        self._trades = trade_service or TradeService(session)
        self._evidence_provider = evidence_provider

    def apply(
        self,
        *,
        order_id: uuid.UUID,
        execution: Execution,
        quote_timestamp: datetime,
        match_pass: int,
    ) -> PaperFill:
        self._validate_input(order_id, execution, quote_timestamp, match_pass)
        order = self._session.scalar(
            select(PaperOrder)
            .where(PaperOrder.id == order_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if order is None:
            raise PaperTradingError("order_not_found", "paper order does not exist")
        retry_exists = (
            self._session.scalar(
                select(PaperMatchPass.id).where(
                    PaperMatchPass.order_id == order.id,
                    PaperMatchPass.quote_timestamp == quote_timestamp,
                    PaperMatchPass.match_pass == match_pass,
                )
            )
            is not None
        )
        self._validate_execution(order, execution, check_remaining=not retry_exists)
        evidence = self._evidence_provider(
            order_id=order_id,
            quote_timestamp=quote_timestamp,
            match_pass=match_pass,
            execution=execution,
        )
        evidence = self._validate_evidence(order, execution, quote_timestamp, match_pass, evidence)

        retry = self._existing_pass(
            order=order,
            execution=execution,
            quote_timestamp=quote_timestamp,
            match_pass=match_pass,
            evidence=evidence,
        )
        if retry is not None:
            return retry

        if order.status not in {OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED}:
            raise PaperTradingError("order_not_open", "paper order is not open for matching")
        account = self._session.scalar(
            select(PaperAccount)
            .where(
                PaperAccount.id == order.account_id,
                PaperAccount.user_id == order.user_id,
                PaperAccount.generation == order.account_generation,
                PaperAccount.status == PaperAccountStatus.ACTIVE,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if account is None:
            raise PaperTradingError("stale_account_generation", "account generation has changed")
        self._validate_execution(order, execution)
        self._validate_projection_capacity(order, execution)

        allocations: list[tuple[PaperLotReservation, PaperHoldingLot]] = []
        if order.side is OrderSide.SELL:
            allocations = self._lock_sell_allocations(order, account, execution.quantity)

        prior_gross, prior_fees = self._prior_totals(order)
        gross = _four(execution.price * execution.quantity)
        cumulative_fees = self._fees.calculate(
            side=order.side.value,
            gross=prior_gross + gross,
            commission_rate=cast(Decimal, account.commission_rate),
            minimum_commission=cast(Decimal, account.minimum_commission),
        )
        incremental = _fee_delta(cumulative_fees, prior_fees)
        executed_at = self._current_time()
        trade_id = uuid.uuid4()
        fill = PaperFill(
            order_id=order.id,
            fill_seq=self._next_fill_seq(order),
            quantity=execution.quantity,
            price=execution.price,
            gross_amount=gross,
            commission=incremental.commission,
            stamp_duty=incremental.stamp_duty,
            transfer_fee=incremental.transfer_fee,
            quote_timestamp=quote_timestamp,
            quote_source=evidence.quote.source,
            executed_at=executed_at,
            trade_id=trade_id,
        )
        pass_row = PaperMatchPass(
            order_id=order.id,
            quote_timestamp=quote_timestamp,
            match_pass=match_pass,
            quote_source=evidence.quote.source,
            snapshot_summary=evidence.quote.model_dump(mode="json"),
            consumed_levels=[level.model_dump(mode="json") for level in evidence.consumed_levels],
            matched_quantity=execution.quantity,
        )
        self._session.add_all([pass_row, fill])
        self._session.flush()
        pass_row.fill_id = fill.id

        if order.side is OrderSide.BUY:
            remaining_cash = self._settle_buy(
                account=account,
                order=order,
                fill=fill,
                gross=gross,
                fees=incremental,
                prior_gross=prior_gross,
                cumulative_fees=cumulative_fees,
                executed_at=executed_at,
            )
        else:
            remaining_quantity = self._settle_sell(
                account=account,
                order=order,
                fill=fill,
                gross=gross,
                fees=incremental,
                allocations=allocations,
            )

        old_filled = int(order.filled_quantity)
        new_filled = old_filled + execution.quantity
        order.filled_quantity = new_filled  # type: ignore[assignment]
        order.avg_fill_price = _four((prior_gross + gross) / new_filled)  # type: ignore[assignment]
        terminal = new_filled == int(order.quantity)
        order.status = OrderStatus.FILLED if terminal else OrderStatus.PARTIALLY_FILLED  # type: ignore[assignment]
        order.completed_at = executed_at if terminal else None  # type: ignore[assignment]
        order.reserved_cash = remaining_cash if order.side is OrderSide.BUY else Decimal("0.00")  # type: ignore[assignment]
        order.reserved_quantity = remaining_quantity if order.side is OrderSide.SELL else 0  # type: ignore[assignment]

        self._trades.create(
            user_id=str(order.user_id),
            ts_code=cast(str, order.ts_code),
            name=cast(str, order.name),
            ttype=TradeType.BUY if order.side is OrderSide.BUY else TradeType.SELL,
            quantity=execution.quantity,
            price=execution.price,
            trade_date=executed_at.astimezone(SHANGHAI).date(),
            note=f"paper-order:{order.id}:fill:{fill.id}",
            trade_id=str(trade_id),
            paper_account_id=cast(uuid.UUID, order.account_id),
            paper_account_generation=cast(int, order.account_generation),
        )
        self._session.flush()
        return fill

    def _settle_buy(
        self,
        *,
        account: PaperAccount,
        order: PaperOrder,
        fill: PaperFill,
        gross: Decimal,
        fees: FeeBreakdown,
        prior_gross: Decimal,
        cumulative_fees: FeeBreakdown,
        executed_at: datetime,
    ) -> Decimal:
        actual = _money(gross + fees.total)
        frozen = _money(cast(Decimal, account.frozen_cash))
        if actual > frozen:
            raise PaperTradingError("insufficient_reservation", "buy reservation is insufficient")
        self._accounts.append_ledger(
            account=account,
            kind="fill_debit",
            amount=-actual,
            available_after=_money(cast(Decimal, account.available_cash)),
            frozen_after=_money(frozen - actual),
            business_key=f"fill-debit:{fill.id}",
            order_id=cast(uuid.UUID, order.id),
            fill_id=cast(uuid.UUID, fill.id),
        )

        remaining = int(order.quantity) - int(order.filled_quantity) - int(fill.quantity)
        required = self._remaining_buy_reservation(
            order=order,
            account=account,
            remaining=remaining,
            prior_gross=prior_gross + gross,
            prior_fees=cumulative_fees,
        )
        frozen = _money(cast(Decimal, account.frozen_cash))
        if required > frozen:
            raise PaperTradingError(
                "insufficient_reservation", "remaining buy reservation is insufficient"
            )
        release = _money(frozen - required)
        if release:
            self._accounts.append_ledger(
                account=account,
                kind="reservation_release",
                amount=release,
                available_after=_money(cast(Decimal, account.available_cash) + release),
                frozen_after=required,
                business_key=f"fill-release:{fill.id}",
                order_id=cast(uuid.UUID, order.id),
                fill_id=cast(uuid.UUID, fill.id),
            )
        self._create_buy_lot(account=account, order=order, fill=fill, actual=actual, at=executed_at)
        return required

    def _create_buy_lot(
        self,
        *,
        account: PaperAccount,
        order: PaperOrder,
        fill: PaperFill,
        actual: Decimal,
        at: datetime,
    ) -> None:
        source = self._session.execute(
            select(PaperFill, PaperOrder)
            .join(PaperOrder, PaperOrder.id == PaperFill.order_id)
            .where(PaperFill.id == fill.id)
            .with_for_update(of=PaperFill)
        ).one_or_none()
        if source is None:
            raise PaperTradingError("invalid_holding_provenance", "source fill is missing")
        source_fill, source_order = source
        if (
            source_fill.order_id != order.id
            or source_order.account_id != account.id
            or source_order.user_id != account.user_id
            or source_order.account_generation != account.generation
            or order.account_id != account.id
            or order.account_generation != account.generation
        ):
            raise PaperTradingError(
                "invalid_holding_provenance", "holding lot provenance is inconsistent"
            )
        lot = self._build_buy_lot(
            account=account,
            order=order,
            fill=fill,
            actual=actual,
            at=at,
        )
        if (
            lot.account_id != account.id
            or lot.generation != account.generation
            or lot.source_fill_id != fill.id
        ):
            raise PaperTradingError(
                "invalid_holding_provenance", "holding lot target is inconsistent"
            )
        self._session.add(lot)

    def _build_buy_lot(
        self,
        *,
        account: PaperAccount,
        order: PaperOrder,
        fill: PaperFill,
        actual: Decimal,
        at: datetime,
    ) -> PaperHoldingLot:
        local_date = at.astimezone(SHANGHAI).date()
        return PaperHoldingLot(
            account_id=account.id,
            generation=account.generation,
            ts_code=order.ts_code,
            name=order.name,
            source_fill_id=fill.id,
            original_quantity=fill.quantity,
            remaining_quantity=fill.quantity,
            frozen_quantity=0,
            unit_cost=_four(actual / int(fill.quantity)),
            available_on=self._calendar.next_open_date(local_date),
        )

    def _settle_sell(
        self,
        *,
        account: PaperAccount,
        order: PaperOrder,
        fill: PaperFill,
        gross: Decimal,
        fees: FeeBreakdown,
        allocations: list[tuple[PaperLotReservation, PaperHoldingLot]],
    ) -> int:
        left = int(fill.quantity)
        for reservation, lot in allocations:
            used = min(left, int(reservation.remaining_quantity))
            reservation.remaining_quantity = int(reservation.remaining_quantity) - used  # type: ignore[assignment]
            lot.frozen_quantity = int(lot.frozen_quantity) - used  # type: ignore[assignment]
            lot.remaining_quantity = int(lot.remaining_quantity) - used  # type: ignore[assignment]
            left -= used
        if left:
            raise PaperTradingError("insufficient_reservation", "sell reservation is insufficient")
        remaining_reserved = int(order.reserved_quantity) - int(fill.quantity)
        proceeds = _money(gross - fees.total)
        self._accounts.append_ledger(
            account=account,
            kind="fill_credit",
            amount=proceeds,
            available_after=_money(cast(Decimal, account.available_cash) + proceeds),
            frozen_after=_money(cast(Decimal, account.frozen_cash)),
            business_key=f"fill-credit:{fill.id}",
            order_id=cast(uuid.UUID, order.id),
            fill_id=cast(uuid.UUID, fill.id),
        )
        return remaining_reserved

    def _lock_sell_allocations(
        self, order: PaperOrder, account: PaperAccount, quantity: int
    ) -> list[tuple[PaperLotReservation, PaperHoldingLot]]:
        rows = self._session.execute(
            select(PaperLotReservation, PaperHoldingLot, PaperFill, PaperOrder)
            .join(PaperHoldingLot, PaperHoldingLot.id == PaperLotReservation.lot_id)
            .join(PaperFill, PaperFill.id == PaperHoldingLot.source_fill_id)
            .join(PaperOrder, PaperOrder.id == PaperFill.order_id)
            .where(
                PaperLotReservation.order_id == order.id,
                PaperLotReservation.remaining_quantity > 0,
            )
            .order_by(PaperHoldingLot.created_at, PaperHoldingLot.id)
            .with_for_update(of=(PaperLotReservation, PaperHoldingLot))
        ).all()
        result: list[tuple[PaperLotReservation, PaperHoldingLot]] = []
        available = 0
        for reservation, lot, _source_fill, source_order in rows:
            if (
                reservation.account_id != account.id
                or reservation.account_generation != account.generation
                or lot.account_id != account.id
                or lot.generation != account.generation
                or source_order.account_id != account.id
                or source_order.user_id != account.user_id
                or source_order.account_generation != account.generation
            ):
                raise PaperTradingError(
                    "invalid_holding_provenance", "holding lot provenance is inconsistent"
                )
            if int(lot.frozen_quantity) < int(reservation.remaining_quantity):
                raise PaperTradingError("invalid_holding_provenance", "lot freeze is inconsistent")
            result.append((reservation, lot))
            available += int(reservation.remaining_quantity)
        if available < quantity or int(order.reserved_quantity) < quantity:
            raise PaperTradingError("insufficient_reservation", "sell reservation is insufficient")
        return result

    def _remaining_buy_reservation(
        self,
        *,
        order: PaperOrder,
        account: PaperAccount,
        remaining: int,
        prior_gross: Decimal,
        prior_fees: FeeBreakdown,
    ) -> Decimal:
        if remaining == 0:
            return Decimal("0.00")
        if order.order_type is OrderType.LIMIT:
            maximum_price = cast(Decimal, order.limit_price)
        else:
            try:
                maximum_price = Decimal(str(order.quote_snapshot["daily_upper_bound"]))
            except (KeyError, TypeError, ValueError):
                raise PaperTradingError(
                    "invalid_quote_snapshot", "confirmed market order lacks daily upper bound"
                ) from None
        remaining_gross = _four(maximum_price * remaining)
        projected = self._fees.calculate(
            side=OrderSide.BUY.value,
            gross=prior_gross + remaining_gross,
            commission_rate=cast(Decimal, account.commission_rate),
            minimum_commission=cast(Decimal, account.minimum_commission),
        )
        remaining_fees = _fee_delta(projected, prior_fees)
        return _money(remaining_gross + remaining_fees.total)

    def _prior_totals(self, order: PaperOrder) -> tuple[Decimal, FeeBreakdown]:
        rows = self._session.scalars(
            select(PaperFill).where(PaperFill.order_id == order.id).order_by(PaperFill.fill_seq)
        ).all()
        return (
            sum((cast(Decimal, row.gross_amount) for row in rows), Decimal(0)),
            FeeBreakdown(
                commission=sum((cast(Decimal, row.commission) for row in rows), Decimal(0)),
                stamp_duty=sum((cast(Decimal, row.stamp_duty) for row in rows), Decimal(0)),
                transfer_fee=sum((cast(Decimal, row.transfer_fee) for row in rows), Decimal(0)),
            ),
        )

    def _next_fill_seq(self, order: PaperOrder) -> int:
        latest = self._session.scalars(
            select(PaperFill.fill_seq)
            .where(PaperFill.order_id == order.id)
            .order_by(PaperFill.fill_seq.desc())
            .limit(1)
        ).first()
        return int(latest or 0) + 1

    def _existing_pass(
        self,
        *,
        order: PaperOrder,
        execution: Execution,
        quote_timestamp: datetime,
        match_pass: int,
        evidence: MatchQuoteEvidence,
    ) -> PaperFill | None:
        row = self._session.scalar(
            select(PaperMatchPass).where(
                PaperMatchPass.order_id == order.id,
                PaperMatchPass.quote_timestamp == quote_timestamp,
                PaperMatchPass.match_pass == match_pass,
            )
        )
        if row is None:
            return None
        fill = self._session.get(PaperFill, row.fill_id) if row.fill_id else None
        if (
            fill is None
            or fill.order_id != order.id
            or int(fill.quantity) != execution.quantity
            or cast(Decimal, fill.price) != execution.price
            or int(row.matched_quantity) != execution.quantity
            or row.quote_source != evidence.quote.source
            or row.snapshot_summary != evidence.quote.model_dump(mode="json")
            or row.consumed_levels
            != [level.model_dump(mode="json") for level in evidence.consumed_levels]
        ):
            raise PaperTradingError(
                "match_pass_conflict", "match-pass watermark conflicts with execution"
            )
        return fill

    def _validate_evidence(
        self,
        order: PaperOrder,
        execution: Execution,
        quote_timestamp: datetime,
        match_pass: int,
        evidence: MatchQuoteEvidence,
    ) -> MatchQuoteEvidence:
        if not isinstance(evidence, MatchQuoteEvidence):
            raise PaperTradingError("invalid_match_evidence", "match evidence is inconsistent")
        raw_source = evidence.quote.source
        if not isinstance(raw_source, str):
            raise PaperTradingError("invalid_match_evidence", "match evidence is inconsistent")
        source = raw_source.strip()
        levels = evidence.consumed_levels
        index = evidence.execution_index
        remaining_before_match = evidence.remaining_before_match
        if (
            evidence.quote.quoted_at != quote_timestamp
            or evidence.quote.ts_code != order.ts_code
            or not source
            or len(source) > 64
            or isinstance(index, bool)
            or not isinstance(index, int)
            or index < 0
            or index >= len(levels)
            or isinstance(remaining_before_match, bool)
            or not isinstance(remaining_before_match, int)
            or remaining_before_match <= 0
        ):
            raise PaperTradingError("invalid_match_evidence", "match evidence is inconsistent")
        try:
            expected = match_visible_depth(
                side=cast(OrderSide, order.side),
                order_type=cast(OrderType, order.order_type),
                remaining=remaining_before_match,
                limit_price=cast(Decimal | None, order.limit_price),
                quote=evidence.quote,
            )
        except PaperTradingError as exc:
            raise PaperTradingError(
                "invalid_match_evidence", "actual quote cannot support execution"
            ) from exc
        if not expected or tuple(expected) != levels or levels[index] != execution:
            raise PaperTradingError("invalid_match_evidence", "match evidence is inconsistent")
        if source != raw_source:
            evidence = evidence.model_copy(
                update={"quote": evidence.quote.model_copy(update={"source": source})}
            )
        history = self._session.scalars(
            select(PaperMatchPass)
            .where(PaperMatchPass.order_id == order.id)
            .order_by(PaperMatchPass.match_pass)
        ).all()
        watermarks = [int(row.match_pass) for row in history]
        if watermarks != list(range(1, len(history) + 1)) or any(
            left.quote_timestamp > right.quote_timestamp
            for left, right in zip(history, history[1:])
        ):
            raise PaperTradingError(
                "invalid_match_evidence", "match evidence history is inconsistent"
            )
        rows = [row for row in history if row.quote_timestamp == quote_timestamp]
        prior_rows = [row for row in rows if int(row.match_pass) < match_pass]
        current_rows = [row for row in rows if int(row.match_pass) == match_pass]
        later_rows = [row for row in rows if int(row.match_pass) > match_pass]
        if (
            len(prior_rows) != index
            or len(current_rows) > 1
            or (later_rows and not current_rows)
            or len(rows) > len(levels)
            or (not current_rows and match_pass != len(history) + 1)
            or (
                not current_rows and bool(history) and quote_timestamp < history[-1].quote_timestamp
            )
        ):
            raise PaperTradingError(
                "invalid_match_evidence", "match evidence history is inconsistent"
            )
        for position, row in enumerate(rows):
            if current_rows and row.id == current_rows[0].id:
                continue
            fill = self._session.get(PaperFill, row.fill_id) if row.fill_id else None
            expected_level = levels[position]
            if (
                fill is None
                or fill.order_id != order.id
                or cast(Decimal, fill.price) != expected_level.price
                or int(fill.quantity) != expected_level.quantity
                or int(row.matched_quantity) != expected_level.quantity
                or row.quote_source != evidence.quote.source
                or row.snapshot_summary != evidence.quote.model_dump(mode="json")
                or row.consumed_levels != [level.model_dump(mode="json") for level in levels]
            ):
                raise PaperTradingError(
                    "match_pass_conflict" if current_rows else "invalid_match_evidence",
                    "match evidence history is inconsistent",
                )
        first_snapshot_pass = int(rows[0].match_pass) if rows else match_pass
        historical_filled = 0
        for row in history:
            if int(row.match_pass) >= first_snapshot_pass:
                break
            fill = self._session.get(PaperFill, row.fill_id) if row.fill_id else None
            if (
                fill is None
                or fill.order_id != order.id
                or int(fill.quantity) != int(row.matched_quantity)
                or int(fill.quantity) <= 0
            ):
                raise PaperTradingError(
                    "invalid_match_evidence", "match evidence history is inconsistent"
                )
            historical_filled += int(fill.quantity)
        if remaining_before_match != int(order.quantity) - historical_filled:
            raise PaperTradingError(
                "match_pass_conflict" if current_rows else "invalid_match_evidence",
                "match evidence history is inconsistent",
            )
        return evidence

    @staticmethod
    def _validate_input(
        order_id: uuid.UUID,
        execution: Execution,
        quote_timestamp: datetime,
        match_pass: int,
    ) -> None:
        if not isinstance(order_id, uuid.UUID):
            raise PaperTradingError("invalid_settlement_input", "order_id must be a UUID")
        if not isinstance(execution, Execution):
            raise PaperTradingError("invalid_settlement_input", "execution must be an Execution")
        if (
            not isinstance(quote_timestamp, datetime)
            or quote_timestamp.tzinfo is None
            or quote_timestamp.utcoffset() is None
        ):
            raise PaperTradingError(
                "invalid_settlement_input", "quote_timestamp must be timezone-aware"
            )
        if isinstance(match_pass, bool) or not isinstance(match_pass, int) or match_pass <= 0:
            raise PaperTradingError("invalid_settlement_input", "match_pass must be positive")

    @staticmethod
    def _validate_execution(
        order: PaperOrder, execution: Execution, *, check_remaining: bool = True
    ) -> None:
        price = execution.price
        if (
            not isinstance(price, Decimal)
            or not price.is_finite()
            or price <= 0
            or price != _four(price)
            or price >= Decimal("100000000000000")
        ):
            raise PaperTradingError("invalid_execution_price", "execution price is invalid")
        try:
            price_tick = Decimal(str(order.quote_snapshot["price_tick"]))
        except (KeyError, InvalidOperation, ValueError):
            raise PaperTradingError(
                "invalid_quote_snapshot", "confirmed order lacks price tick"
            ) from None
        if not price_tick.is_finite() or price_tick <= 0 or price % price_tick != 0:
            raise PaperTradingError("invalid_execution_price", "execution price is off tick")
        remaining = int(order.quantity) - int(order.filled_quantity)
        if execution.quantity > 2_147_483_647 or price * execution.quantity >= Decimal(
            "100000000000000"
        ):
            raise PaperTradingError(
                "invalid_execution_amount", "execution amount exceeds projection capacity"
            )
        if check_remaining and execution.quantity > remaining:
            raise PaperTradingError(
                "execution_quantity_exceeds_remaining", "execution exceeds remaining order quantity"
            )
        if order.order_type is OrderType.LIMIT:
            limit = cast(Decimal, order.limit_price)
            wrong = (order.side is OrderSide.BUY and execution.price > limit) or (
                order.side is OrderSide.SELL and execution.price < limit
            )
            if wrong:
                raise PaperTradingError(
                    "execution_price_mismatch", "execution violates limit price"
                )
        snapshot = cast(dict[str, object], order.quote_snapshot)
        try:
            lower = Decimal(str(snapshot["daily_lower_bound"]))
            upper = Decimal(str(snapshot["daily_upper_bound"]))
        except (KeyError, InvalidOperation, ValueError):
            if order.order_type is OrderType.MARKET:
                raise PaperTradingError(
                    "invalid_quote_snapshot", "confirmed market order lacks daily price bounds"
                ) from None
            return
        if not lower.is_finite() or not upper.is_finite() or lower <= 0 or lower > upper:
            raise PaperTradingError("invalid_quote_snapshot", "daily price bounds are invalid")
        if execution.price < lower or execution.price > upper:
            raise PaperTradingError(
                "execution_price_mismatch", "execution violates confirmed daily price bounds"
            )

    def _validate_projection_capacity(self, order: PaperOrder, execution: Execution) -> None:
        position = self._session.scalar(
            select(Position).where(
                Position.user_id == order.user_id,
                Position.ts_code == order.ts_code,
                Position.paper_account_id == order.account_id,
                Position.paper_account_generation == order.account_generation,
            )
        )
        current_quantity = int(position.quantity) if position is not None else 0
        current_total = cast(Decimal, position.total_cost) if position is not None else Decimal(0)
        if order.side is OrderSide.BUY and (
            current_quantity + execution.quantity > 2_147_483_647
            or current_total + execution.price * execution.quantity
            >= Decimal("1000000000000000000")
        ):
            raise PaperTradingError(
                "invalid_execution_amount", "execution exceeds position projection capacity"
            )

    def _current_time(self) -> datetime:
        value = self._now()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise PaperTradingError(
                "invalid_settlement_time", "settlement time must be timezone-aware"
            )
        return value


def _quote_source(order: PaperOrder) -> str:
    value = order.quote_snapshot.get("source")
    return value if isinstance(value, str) and value.strip() else "confirmed-quote"


def _fee_delta(total: FeeBreakdown, prior: FeeBreakdown) -> FeeBreakdown:
    values = (
        total.commission - prior.commission,
        total.stamp_duty - prior.stamp_duty,
        total.transfer_fee - prior.transfer_fee,
    )
    if any(value < 0 for value in values):
        raise PaperTradingError("invalid_fee_state", "cumulative fees moved backwards")
    return FeeBreakdown(commission=values[0], stamp_duty=values[1], transfer_fee=values[2])


def _money(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def _four(value: Decimal) -> Decimal:
    return value.quantize(_FOUR_PLACES, rounding=ROUND_HALF_UP)
