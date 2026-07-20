"""Read-only invariant checks for one simulated-account generation."""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import cast

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.paper_account import (
    PaperAccount,
    PaperAccountStatus,
    PaperCashLedger,
    PaperHoldingLot,
)
from app.models.paper_order import (
    OrderSide,
    OrderStatus,
    PaperFill,
    PaperLotReservation,
    PaperOrder,
)
from app.models.position import Position
from app.models.trade import Trade, TradeType
from app.services.paper_trading.fee_schedule import FeeSchedule
from app.services.paper_trading.types import FeeBreakdown
from app.services.portfolio_recompute import TradeInput, recompute_position_from_trades

_CENT = Decimal("0.01")
_FOUR_PLACES = Decimal("0.0001")
_KNOWN_LEDGER_KINDS = {
    "initial_deposit",
    "initial_deposit_reversal",
    "order_freeze",
    "reservation_release",
    "fill_debit",
    "fill_credit",
}


class ReconciliationViolation(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)

    code: str
    account_id: uuid.UUID
    details: dict[str, object]


def reconcile_account(
    session: Session, account_id: uuid.UUID, *, require_active: bool = False
) -> list[ReconciliationViolation] | None:
    """Check one account generation and suspend it when any invariant is broken."""
    account = session.scalar(
        select(PaperAccount)
        .where(PaperAccount.id == account_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if account is None:
        return [_violation(account_id, "account_not_found")]
    if require_active and account.status is not PaperAccountStatus.ACTIVE:
        return None

    checks = (
        _check_cash_non_negative,
        _check_fill_quantity,
        _check_lot_quantities,
        _check_lots_against_fills,
        _check_share_conservation,
        _check_trade_position_projection,
        _check_cash_authority,
        _check_ledger_balance,
        _check_reservations,
    )
    violations = [item for check in checks for item in check(session, account)]
    violations.sort(key=_sort_key)
    if violations and account.status is PaperAccountStatus.ACTIVE:
        account.status = PaperAccountStatus.SUSPENDED
        session.flush()
    return violations


def _check_cash_non_negative(
    session: Session, account: PaperAccount
) -> list[ReconciliationViolation]:
    del session
    result: list[ReconciliationViolation] = []
    if cast(Decimal, account.available_cash) < 0:
        result.append(
            _violation(account.id, "cash_available_negative", value=str(account.available_cash))
        )
    if cast(Decimal, account.frozen_cash) < 0:
        result.append(
            _violation(account.id, "cash_frozen_negative", value=str(account.frozen_cash))
        )
    return result


def _orders(session: Session, account: PaperAccount) -> list[PaperOrder]:
    return list(
        session.scalars(
            select(PaperOrder)
            .where(
                PaperOrder.account_id == account.id,
                PaperOrder.account_generation == account.generation,
            )
            .order_by(PaperOrder.id)
        ).all()
    )


def _check_fill_quantity(session: Session, account: PaperAccount) -> list[ReconciliationViolation]:
    result: list[ReconciliationViolation] = []
    for order in _orders(session, account):
        fills = session.scalars(
            select(PaperFill).where(PaperFill.order_id == order.id).order_by(PaperFill.fill_seq)
        ).all()
        total = sum(int(fill.quantity) for fill in fills)
        sequences = [int(fill.fill_seq) for fill in fills]
        if int(order.filled_quantity) > int(order.quantity):
            result.append(
                _violation(
                    account.id,
                    "order_filled_quantity_exceeds_order",
                    order_id=str(order.id),
                    recorded_quantity=int(order.filled_quantity),
                    order_quantity=int(order.quantity),
                )
            )
        if total > int(order.quantity):
            result.append(
                _violation(
                    account.id,
                    "fill_quantity_exceeds_order",
                    order_id=str(order.id),
                    fill_quantity=total,
                    order_quantity=int(order.quantity),
                )
            )
        if total != int(order.filled_quantity):
            result.append(
                _violation(
                    account.id,
                    "order_filled_quantity_mismatch",
                    order_id=str(order.id),
                    fill_quantity=total,
                    recorded_quantity=int(order.filled_quantity),
                )
            )
        if sequences != list(range(1, len(sequences) + 1)):
            result.append(
                _violation(
                    account.id,
                    "fill_sequence_invalid",
                    order_id=str(order.id),
                    sequences=sequences,
                )
            )
    return result


def _lots(session: Session, account: PaperAccount) -> list[PaperHoldingLot]:
    return list(
        session.scalars(
            select(PaperHoldingLot)
            .where(
                PaperHoldingLot.account_id == account.id,
                PaperHoldingLot.generation == account.generation,
            )
            .order_by(PaperHoldingLot.id)
        ).all()
    )


def _check_lot_quantities(session: Session, account: PaperAccount) -> list[ReconciliationViolation]:
    result: list[ReconciliationViolation] = []
    for lot in _lots(session, account):
        original = int(lot.original_quantity)
        remaining = int(lot.remaining_quantity)
        frozen = int(lot.frozen_quantity)
        if (
            original <= 0
            or remaining < 0
            or remaining > original
            or frozen < 0
            or frozen > remaining
        ):
            result.append(
                _violation(
                    account.id,
                    "lot_quantity_invalid",
                    lot_id=str(lot.id),
                    original=original,
                    remaining=remaining,
                    frozen=frozen,
                )
            )
    return result


def _check_lots_against_fills(
    session: Session, account: PaperAccount
) -> list[ReconciliationViolation]:
    result: list[ReconciliationViolation] = []
    lots = _lots(session, account)
    lot_by_fill = {cast(uuid.UUID, lot.source_fill_id): lot for lot in lots}
    fills = session.scalars(
        select(PaperFill)
        .join(PaperOrder, PaperOrder.id == PaperFill.order_id)
        .where(
            PaperOrder.account_id == account.id,
            PaperOrder.account_generation == account.generation,
        )
        .order_by(PaperFill.id)
    ).all()
    for fill in fills:
        order = session.get(PaperOrder, fill.order_id)
        lot = lot_by_fill.get(cast(uuid.UUID, fill.id))
        if order is not None and order.side is OrderSide.BUY:
            if (
                lot is None
                or lot.ts_code != order.ts_code
                or int(lot.original_quantity) != int(fill.quantity)
            ):
                result.append(
                    _violation(
                        account.id,
                        "buy_fill_lot_mismatch",
                        fill_id=str(fill.id),
                        lot_id=str(lot.id) if lot is not None else None,
                    )
                )
        elif lot is not None:
            result.append(
                _violation(
                    account.id,
                    "lot_source_fill_invalid",
                    fill_id=str(fill.id),
                    lot_id=str(lot.id),
                )
            )
    expected_fee_by_fill = _expected_fill_fees(session, account)
    for lot in lots:
        source_fill = session.get(PaperFill, lot.source_fill_id)
        order = session.get(PaperOrder, source_fill.order_id) if source_fill is not None else None
        if (
            source_fill is None
            or order is None
            or order.side is not OrderSide.BUY
            or order.account_id != account.id
            or order.account_generation != account.generation
            or order.ts_code != lot.ts_code
            or int(source_fill.quantity) != int(lot.original_quantity)
        ):
            candidate = _violation(
                account.id,
                "lot_source_fill_invalid",
                fill_id=str(lot.source_fill_id),
                lot_id=str(lot.id),
            )
            if candidate not in result:
                result.append(candidate)
            continue
        expected_fees = expected_fee_by_fill.get(cast(uuid.UUID, source_fill.id))
        if expected_fees is None:
            continue
        expected_cost = _four(
            _money(cast(Decimal, source_fill.gross_amount) + expected_fees.total)
            / int(source_fill.quantity)
        )
        if cast(Decimal, lot.unit_cost) != expected_cost:
            result.append(
                _violation(
                    account.id,
                    "lot_unit_cost_mismatch",
                    lot_id=str(lot.id),
                    fill_id=str(source_fill.id),
                    expected_unit_cost=str(expected_cost),
                    actual_unit_cost=str(lot.unit_cost),
                )
            )
    return result


def _check_trade_position_projection(
    session: Session, account: PaperAccount
) -> list[ReconciliationViolation]:
    result: list[ReconciliationViolation] = []
    fills = session.scalars(
        select(PaperFill)
        .join(PaperOrder, PaperOrder.id == PaperFill.order_id)
        .where(
            PaperOrder.account_id == account.id,
            PaperOrder.account_generation == account.generation,
        )
        .order_by(PaperFill.id)
    ).all()
    fill_ids = {str(fill.trade_id): fill for fill in fills}
    trades = list(
        session.scalars(
            select(Trade)
            .where(
                Trade.paper_account_id == account.id,
                Trade.paper_account_generation == account.generation,
            )
            .order_by(Trade.ts_code, Trade.trade_date, Trade.created_at, Trade.id)
        ).all()
    )
    trades_by_id = {cast(str, row.id): row for row in trades}
    for trade_id, fill in sorted(fill_ids.items()):
        trade = trades_by_id.get(trade_id)
        order = session.get(PaperOrder, fill.order_id)
        if (
            trade is None
            or order is None
            or trade.ts_code != order.ts_code
            or trade.quantity != fill.quantity
            or trade.price != fill.price
            or trade.type.value != order.side.value
        ):
            result.append(
                _violation(
                    account.id, "fill_trade_mismatch", fill_id=str(fill.id), trade_id=trade_id
                )
            )
    for trade in trades:
        if trade.id not in fill_ids:
            result.append(_violation(account.id, "orphan_paper_trade", trade_id=trade.id))

    by_symbol: dict[str, list[Trade]] = defaultdict(list)
    for trade in trades:
        by_symbol[cast(str, trade.ts_code)].append(trade)
    positions = list(
        session.scalars(
            select(Position).where(
                Position.paper_account_id == account.id,
                Position.paper_account_generation == account.generation,
            )
        ).all()
    )
    position_by_symbol = {cast(str, row.ts_code): row for row in positions}
    for symbol in sorted(set(by_symbol) | set(position_by_symbol)):
        rows = by_symbol.get(symbol, [])
        position = position_by_symbol.get(symbol)
        if not rows:
            result.append(_violation(account.id, "position_projection_mismatch", ts_code=symbol))
            continue
        state = recompute_position_from_trades(
            [
                TradeInput(
                    type=cast(TradeType, row.type),
                    quantity=cast(int, row.quantity),
                    price=cast(Decimal, row.price),
                    trade_date=cast(date, row.trade_date),
                )
                for row in rows
            ]
        )
        if (
            position is None
            or int(position.quantity) != state.quantity
            or cast(Decimal, position.avg_cost) != state.avg_cost
            or cast(Decimal, position.total_cost) != state.total_cost
            or cast(Decimal, position.realized_pnl) != state.realized_pnl
        ):
            result.append(_violation(account.id, "position_projection_mismatch", ts_code=symbol))
    return result


def _check_share_conservation(
    session: Session, account: PaperAccount
) -> list[ReconciliationViolation]:
    """Reconcile immutable executions to remaining lots and scoped positions."""
    net_by_symbol: dict[str, int] = defaultdict(int)
    fill_rows = session.execute(
        select(PaperFill.quantity, PaperOrder.side, PaperOrder.ts_code)
        .join(PaperOrder, PaperOrder.id == PaperFill.order_id)
        .where(
            PaperOrder.account_id == account.id,
            PaperOrder.account_generation == account.generation,
        )
    ).all()
    for quantity, side, ts_code in fill_rows:
        direction = 1 if side is OrderSide.BUY else -1
        net_by_symbol[str(ts_code)] += direction * int(quantity)

    lots_by_symbol: dict[str, int] = defaultdict(int)
    for lot in _lots(session, account):
        lots_by_symbol[cast(str, lot.ts_code)] += int(lot.remaining_quantity)

    positions = session.scalars(
        select(Position).where(
            Position.paper_account_id == account.id,
            Position.paper_account_generation == account.generation,
        )
    ).all()
    position_by_symbol = {cast(str, row.ts_code): int(row.quantity) for row in positions}

    result: list[ReconciliationViolation] = []
    for symbol in sorted(set(net_by_symbol) | set(lots_by_symbol) | set(position_by_symbol)):
        expected = net_by_symbol.get(symbol, 0)
        actual_lots = lots_by_symbol.get(symbol, 0)
        if actual_lots != expected:
            result.append(
                _violation(
                    account.id,
                    "lot_share_balance_mismatch",
                    ts_code=symbol,
                    expected_net_quantity=expected,
                    actual_lot_quantity=actual_lots,
                )
            )
        actual_position = position_by_symbol.get(symbol)
        if actual_position is None or actual_position != expected:
            result.append(
                _violation(
                    account.id,
                    "position_share_balance_mismatch",
                    ts_code=symbol,
                    expected_net_quantity=expected,
                    actual_position_quantity=actual_position,
                )
            )
    return result


def _expected_fill_fees(session: Session, account: PaperAccount) -> dict[uuid.UUID, FeeBreakdown]:
    schedule = FeeSchedule.from_builtin_fixture()
    result: dict[uuid.UUID, FeeBreakdown] = {}
    zero = FeeBreakdown(
        commission=Decimal("0.00"),
        stamp_duty=Decimal("0.00"),
        transfer_fee=Decimal("0.00"),
    )
    for order in _orders(session, account):
        cumulative_gross = Decimal("0.0000")
        prior = zero
        fills = session.scalars(
            select(PaperFill).where(PaperFill.order_id == order.id).order_by(PaperFill.fill_seq)
        ).all()
        for fill in fills:
            cumulative_gross += cast(Decimal, fill.gross_amount)
            cumulative = schedule.calculate(
                side=cast(OrderSide, order.side).value,
                gross=cumulative_gross,
                commission_rate=cast(Decimal, account.commission_rate),
                minimum_commission=cast(Decimal, account.minimum_commission),
            )
            incremental = FeeBreakdown(
                commission=cumulative.commission - prior.commission,
                stamp_duty=cumulative.stamp_duty - prior.stamp_duty,
                transfer_fee=cumulative.transfer_fee - prior.transfer_fee,
            )
            result[cast(uuid.UUID, fill.id)] = incremental
            prior = cumulative
    return result


def _check_cash_authority(session: Session, account: PaperAccount) -> list[ReconciliationViolation]:
    result: list[ReconciliationViolation] = []
    expected_fees = _expected_fill_fees(session, account)
    fill_rows = session.execute(
        select(PaperFill, PaperOrder)
        .join(PaperOrder, PaperOrder.id == PaperFill.order_id)
        .where(
            PaperOrder.account_id == account.id,
            PaperOrder.account_generation == account.generation,
        )
        .order_by(PaperOrder.id, PaperFill.fill_seq)
    ).all()
    fills_by_id = {cast(uuid.UUID, fill.id): (fill, order) for fill, order in fill_rows}
    ledgers = list(
        session.scalars(
            select(PaperCashLedger)
            .where(
                PaperCashLedger.account_id == account.id,
                PaperCashLedger.generation == account.generation,
            )
            .order_by(PaperCashLedger.id)
        ).all()
    )
    primary_by_fill: dict[uuid.UUID, list[PaperCashLedger]] = defaultdict(list)
    for row in ledgers:
        kind = cast(str, row.kind)
        if kind not in _KNOWN_LEDGER_KINDS:
            result.append(
                _violation(
                    account.id,
                    "unknown_ledger_kind",
                    ledger_id=str(row.id),
                    kind=kind,
                )
            )
        if kind in {"fill_debit", "fill_credit"}:
            if row.fill_id is None:
                result.append(
                    _violation(
                        account.id,
                        "fill_ledger_mismatch",
                        ledger_id=str(row.id),
                        reason="missing_fill_id",
                    )
                )
            else:
                primary_by_fill[cast(uuid.UUID, row.fill_id)].append(row)

    expected_total = cast(Decimal, account.initial_cash)
    for fill_id, (fill, order) in fills_by_id.items():
        fees = expected_fees[fill_id]
        stored = FeeBreakdown(
            commission=cast(Decimal, fill.commission),
            stamp_duty=cast(Decimal, fill.stamp_duty),
            transfer_fee=cast(Decimal, fill.transfer_fee),
        )
        if stored != fees:
            result.append(
                _violation(
                    account.id,
                    "fill_fee_mismatch",
                    fill_id=str(fill.id),
                    expected=fees.model_dump(mode="json"),
                    actual=stored.model_dump(mode="json"),
                )
            )
        gross = cast(Decimal, fill.gross_amount)
        if order.side is OrderSide.BUY:
            expected_kind = "fill_debit"
            expected_amount = -_money(gross + fees.total)
            expected_total += expected_amount
        else:
            expected_kind = "fill_credit"
            expected_amount = _money(gross - fees.total)
            expected_total += expected_amount
        candidates = primary_by_fill.get(fill_id, [])
        if not candidates:
            result.append(_violation(account.id, "fill_ledger_missing", fill_id=str(fill.id)))
            continue
        if len(candidates) > 1:
            result.append(
                _violation(
                    account.id,
                    "fill_ledger_duplicate",
                    fill_id=str(fill.id),
                    ledger_ids=sorted(str(row.id) for row in candidates),
                )
            )
            continue
        ledger = candidates[0]
        available_delta = cast(Decimal, ledger.available_after) - cast(
            Decimal, ledger.available_before
        )
        frozen_delta = cast(Decimal, ledger.frozen_after) - cast(Decimal, ledger.frozen_before)
        if (
            ledger.kind != expected_kind
            or ledger.order_id != order.id
            or cast(Decimal, ledger.amount) != expected_amount
            or not _ledger_amount_matches(
                kind=expected_kind,
                amount=expected_amount,
                available_delta=available_delta,
                frozen_delta=frozen_delta,
            )
        ):
            result.append(
                _violation(
                    account.id,
                    "fill_ledger_mismatch",
                    fill_id=str(fill.id),
                    ledger_id=str(ledger.id),
                )
            )

    for fill_id, rows in primary_by_fill.items():
        if fill_id not in fills_by_id:
            for row in rows:
                result.append(
                    _violation(
                        account.id,
                        "fill_ledger_mismatch",
                        ledger_id=str(row.id),
                        fill_id=str(fill_id),
                        reason="unknown_fill",
                    )
                )
    actual_total = cast(Decimal, account.available_cash) + cast(Decimal, account.frozen_cash)
    if actual_total != expected_total:
        result.append(
            _violation(
                account.id,
                "cash_balance_mismatch",
                expected_total=str(expected_total),
                actual_total=str(actual_total),
            )
        )
    return result


def _check_ledger_balance(session: Session, account: PaperAccount) -> list[ReconciliationViolation]:
    rows = session.scalars(
        select(PaperCashLedger)
        .where(
            PaperCashLedger.account_id == account.id,
            PaperCashLedger.generation == account.generation,
        )
        .order_by(PaperCashLedger.created_at, PaperCashLedger.id)
    ).all()
    broken = not rows
    for row in rows:
        before_available = cast(Decimal, row.available_before)
        after_available = cast(Decimal, row.available_after)
        before_frozen = cast(Decimal, row.frozen_before)
        after_frozen = cast(Decimal, row.frozen_after)
        available_delta = after_available - before_available
        frozen_delta = after_frozen - before_frozen
        amount = cast(Decimal, row.amount)
        if cast(str, row.kind) in _KNOWN_LEDGER_KINDS and not _ledger_amount_matches(
            kind=cast(str, row.kind),
            amount=amount,
            available_delta=available_delta,
            frozen_delta=frozen_delta,
        ):
            broken = True
    target = (cast(Decimal, account.available_cash), cast(Decimal, account.frozen_cash))
    if rows and not _has_ledger_path(rows, target=target):
        broken = True
    return [_violation(account.id, "ledger_balance_mismatch")] if broken else []


def _has_ledger_path(rows: Sequence[PaperCashLedger], *, target: tuple[Decimal, Decimal]) -> bool:
    """Validate that ledger edges form one Euler trail from zero to current balance."""
    start = (Decimal("0.00"), Decimal("0.00"))
    outgoing: dict[tuple[Decimal, Decimal], int] = defaultdict(int)
    incoming: dict[tuple[Decimal, Decimal], int] = defaultdict(int)
    graph: dict[tuple[Decimal, Decimal], set[tuple[Decimal, Decimal]]] = defaultdict(set)
    vertices: set[tuple[Decimal, Decimal]] = set()
    for row in rows:
        before = (cast(Decimal, row.available_before), cast(Decimal, row.frozen_before))
        after = (cast(Decimal, row.available_after), cast(Decimal, row.frozen_after))
        outgoing[before] += 1
        incoming[after] += 1
        graph[before].add(after)
        graph[after].add(before)
        vertices.update((before, after))
    for vertex in vertices:
        difference = outgoing[vertex] - incoming[vertex]
        expected = 0
        if start != target and vertex == start:
            expected = 1
        elif start != target and vertex == target:
            expected = -1
        if difference != expected:
            return False
    visited: set[tuple[Decimal, Decimal]] = set()
    pending = [start]
    while pending:
        vertex = pending.pop()
        if vertex in visited:
            continue
        visited.add(vertex)
        pending.extend(graph[vertex] - visited)
    return vertices <= visited and target in vertices


def _ledger_amount_matches(
    *, kind: str, amount: Decimal, available_delta: Decimal, frozen_delta: Decimal
) -> bool:
    if kind == "order_freeze":
        return available_delta == amount and frozen_delta == -amount
    if kind == "reservation_release":
        return available_delta == amount and frozen_delta == -amount
    if kind == "fill_debit":
        return available_delta == 0 and frozen_delta == amount
    if kind in {"initial_deposit", "initial_deposit_reversal", "fill_credit"}:
        return available_delta == amount and frozen_delta == 0
    return True


def _check_reservations(session: Session, account: PaperAccount) -> list[ReconciliationViolation]:
    result: list[ReconciliationViolation] = []
    reservations = list(
        session.scalars(
            select(PaperLotReservation)
            .where(
                PaperLotReservation.account_id == account.id,
                PaperLotReservation.account_generation == account.generation,
            )
            .order_by(PaperLotReservation.order_id, PaperLotReservation.lot_id)
        ).all()
    )
    by_order: dict[uuid.UUID, int] = defaultdict(int)
    by_lot: dict[uuid.UUID, int] = defaultdict(int)
    for row in reservations:
        by_order[cast(uuid.UUID, row.order_id)] += int(row.remaining_quantity)
        by_lot[cast(uuid.UUID, row.lot_id)] += int(row.remaining_quantity)
    terminal = {
        OrderStatus.FILLED,
        OrderStatus.CANCELLED,
        OrderStatus.EXPIRED,
        OrderStatus.REJECTED,
    }
    expected_cash_frozen = Decimal("0.00")
    for order in _orders(session, account):
        expected = by_order.get(cast(uuid.UUID, order.id), 0)
        if order.side is OrderSide.SELL and int(order.reserved_quantity) != expected:
            result.append(
                _violation(account.id, "order_reservation_mismatch", order_id=str(order.id))
            )
        if order.status in terminal and expected:
            result.append(
                _violation(account.id, "terminal_order_has_reservation", order_id=str(order.id))
            )
        if order.side is OrderSide.BUY:
            reserved_cash = cast(Decimal, order.reserved_cash)
            if order.status in terminal and reserved_cash != 0:
                result.append(
                    _violation(account.id, "terminal_order_has_reservation", order_id=str(order.id))
                )
            if order.status not in terminal:
                expected_cash_frozen += reserved_cash
    for lot in _lots(session, account):
        if int(lot.frozen_quantity) != by_lot.get(cast(uuid.UUID, lot.id), 0):
            result.append(_violation(account.id, "lot_reservation_mismatch", lot_id=str(lot.id)))
    if expected_cash_frozen != cast(Decimal, account.frozen_cash):
        result.append(
            _violation(
                account.id,
                "cash_reservation_mismatch",
                expected=str(expected_cash_frozen),
                actual=str(account.frozen_cash),
            )
        )
    return result


def _violation(account_id: object, code: str, **details: object) -> ReconciliationViolation:
    return ReconciliationViolation(
        code=code, account_id=cast(uuid.UUID, account_id), details=details
    )


def _sort_key(row: ReconciliationViolation) -> tuple[str, str]:
    return row.code, repr(sorted(row.details.items()))


def _money(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def _four(value: Decimal) -> Decimal:
    return value.quantize(_FOUR_PLACES, rounding=ROUND_HALF_UP)
