from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, cast
from uuid import UUID
from zoneinfo import ZoneInfo

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.paper_account import (
    PaperAccount,
    PaperAccountStatus,
    PaperCashLedger,
    PaperHoldingLot,
)
from app.models.paper_order import OrderStatus, PaperFill, PaperOrder
from app.models.user import User
from app.router.auth_router import get_current_user_required
from app.schemas.paper_trading import (
    CancelPreviewRead,
    ConfirmationRequest,
    InitialCashUpdate,
    OrderConfirmRequest,
    OrderPreview,
    OrderPreviewRequest,
    PaperAccountRead,
    PaperCashLedgerRead,
    PaperFillRead,
    PaperHoldingRead,
    PaperOrderRead,
    ResetConfirmRequest,
    ResetPreviewRead,
    ResetPreviewRequest,
)
from app.services.paper_trading.account_service import PaperAccountService
from app.services.paper_trading.clock import TradingClock, TushareTradingCalendar
from app.services.paper_trading.errors import PaperTradingError
from app.services.paper_trading.observability import (
    emit_paper_order_span,
    emit_paper_system_span,
)
from app.services.paper_trading.order_service import PaperOrderService
from app.services.paper_trading.quote_provider import TushareRealtimeQuoteProvider
from app.services.paper_trading.rulebook import RuleBook
from app.services.trace_models import Span
from app.services.tushare_factory import build_tushare_service
from app.tasks.paper_trading import dispatch_match_order

router = APIRouter(prefix="/api/v0/paper-trading", tags=["paper-trading"])


def _record_order_span(
    *,
    order_id: UUID,
    name: str,
    started_at: datetime,
    attrs: dict[str, object],
    error: str | None = None,
    parent_id: str | None = None,
) -> Span:
    return emit_paper_order_span(
        order_id=order_id,
        name=name,
        started_at=started_at,
        attrs=attrs,
        error=error,
        parent_id=parent_id,
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


def _fetch_trading_calendar(start: str, end: str) -> pd.DataFrame:
    async def fetch() -> pd.DataFrame:
        service = build_tushare_service()
        try:
            return await service.get_trade_cal(start=start, end=end)
        finally:
            await service.aclose()

    return asyncio.run(fetch())


def get_paper_order_service(
    db: Annotated[Session, Depends(get_db)],
) -> PaperOrderService:
    return PaperOrderService(
        db,
        quote_provider=TushareRealtimeQuoteProvider(),
        clock=TradingClock(TushareTradingCalendar(_fetch_trading_calendar)),
        rulebook=RuleBook.from_builtin_fixture(),
        now=lambda: datetime.now(UTC),
    )


def _business_error(exc: PaperTradingError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": exc.code, "message": str(exc)},
    )


@router.get("/account", response_model=PaperAccountRead)
def get_account(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_required)],
    generation: Annotated[int | None, Query(ge=1)] = None,
) -> PaperAccountRead:
    try:
        account = (
            PaperAccountService(db).get_or_create(user_id=user.id)
            if generation is None
            else _account_for_generation(db, user_id=cast(UUID, user.id), generation=generation)
        )
        snapshot = PaperAccountRead.model_validate(account)
        db.commit()
    except PaperTradingError as exc:
        db.rollback()
        raise _business_error(exc) from exc
    except Exception:
        db.rollback()
        raise
    return snapshot


@router.patch("/account/initial-cash", response_model=PaperAccountRead)
def update_initial_cash(
    payload: InitialCashUpdate,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_required)],
) -> PaperAccountRead:
    try:
        service = PaperAccountService(db)
        service.get_or_create(user_id=user.id)
        account = service.edit_initial_cash_once(
            user_id=user.id,
            initial_cash=payload.initial_cash,
        )
        snapshot = PaperAccountRead.model_validate(account)
        db.commit()
    except PaperTradingError as exc:
        db.rollback()
        raise _business_error(exc) from exc
    except Exception:
        db.rollback()
        raise
    return snapshot


def _account_for_generation(db: Session, *, user_id: UUID, generation: int | None) -> PaperAccount:
    statement = select(PaperAccount).where(PaperAccount.user_id == user_id)
    if generation is None:
        statement = statement.where(PaperAccount.status == PaperAccountStatus.ACTIVE)
    else:
        statement = statement.where(PaperAccount.generation == generation)
    account = db.scalar(statement)
    if account is None:
        raise HTTPException(status_code=404, detail="Paper account not found")
    return account


def _owned_order(
    db: Session, *, user_id: UUID, order_id: UUID, generation: int | None = None
) -> PaperOrder:
    account = _account_for_generation(db, user_id=user_id, generation=generation)
    order = db.scalar(
        select(PaperOrder).where(
            PaperOrder.id == order_id,
            PaperOrder.user_id == user_id,
            PaperOrder.account_id == account.id,
            PaperOrder.account_generation == account.generation,
        )
    )
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@router.get("/orders", response_model=list[PaperOrderRead])
def list_orders(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_required)],
    generation: Annotated[int | None, Query(ge=1)] = None,
) -> list[PaperOrderRead]:
    account = _account_for_generation(db, user_id=cast(UUID, user.id), generation=generation)
    rows = db.scalars(
        select(PaperOrder)
        .where(
            PaperOrder.user_id == user.id,
            PaperOrder.account_id == account.id,
            PaperOrder.account_generation == account.generation,
        )
        .order_by(PaperOrder.created_at.desc(), PaperOrder.id.desc())
    ).all()
    return [PaperOrderRead.model_validate(row) for row in rows]


@router.get("/orders/{order_id}", response_model=PaperOrderRead)
def get_order(
    order_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_required)],
    generation: Annotated[int | None, Query(ge=1)] = None,
) -> PaperOrderRead:
    return PaperOrderRead.model_validate(
        _owned_order(db, user_id=cast(UUID, user.id), order_id=order_id, generation=generation)
    )


@router.get("/holdings", response_model=list[PaperHoldingRead])
def list_holdings(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_required)],
    generation: Annotated[int | None, Query(ge=1)] = None,
) -> list[PaperHoldingRead]:
    account = _account_for_generation(db, user_id=cast(UUID, user.id), generation=generation)
    rows = db.scalars(
        select(PaperHoldingLot)
        .where(
            PaperHoldingLot.account_id == account.id,
            PaperHoldingLot.generation == account.generation,
            PaperHoldingLot.remaining_quantity > 0,
        )
        .order_by(PaperHoldingLot.created_at, PaperHoldingLot.id)
    ).all()
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    grouped: dict[str, dict[str, object]] = {}
    for row in rows:
        item = grouped.setdefault(
            row.ts_code,
            {
                "generation": int(row.generation),
                "ts_code": row.ts_code,
                "name": row.name,
                "quantity": 0,
                "frozen_quantity": 0,
                "sellable_quantity": 0,
                "cost": Decimal("0"),
            },
        )
        quantity = int(row.remaining_quantity)
        item["quantity"] = cast(int, item["quantity"]) + quantity
        item["frozen_quantity"] = cast(int, item["frozen_quantity"]) + int(row.frozen_quantity)
        if row.available_on <= today:
            item["sellable_quantity"] = cast(int, item["sellable_quantity"]) + (
                quantity - int(row.frozen_quantity)
            )
        item["cost"] = cast(Decimal, item["cost"]) + cast(Decimal, row.unit_cost) * quantity
    return [
        PaperHoldingRead.model_validate(
            {
                **item,
                "average_cost": cast(Decimal, item["cost"]) / cast(int, item["quantity"]),
            }
        )
        for item in grouped.values()
    ]


@router.get("/fills", response_model=list[PaperFillRead])
def list_fills(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_required)],
    generation: Annotated[int | None, Query(ge=1)] = None,
) -> list[PaperFillRead]:
    account = _account_for_generation(db, user_id=cast(UUID, user.id), generation=generation)
    rows = db.scalars(
        select(PaperFill)
        .join(PaperOrder, PaperOrder.id == PaperFill.order_id)
        .where(
            PaperOrder.user_id == user.id,
            PaperOrder.account_id == account.id,
            PaperOrder.account_generation == account.generation,
        )
        .order_by(PaperFill.executed_at.desc(), PaperFill.id.desc())
    ).all()
    return [PaperFillRead.model_validate(row) for row in rows]


@router.get("/cash-ledger", response_model=list[PaperCashLedgerRead])
def list_cash_ledger(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_required)],
    generation: Annotated[int | None, Query(ge=1)] = None,
) -> list[PaperCashLedgerRead]:
    account = _account_for_generation(db, user_id=cast(UUID, user.id), generation=generation)
    rows = db.scalars(
        select(PaperCashLedger)
        .where(
            PaperCashLedger.account_id == account.id,
            PaperCashLedger.generation == account.generation,
        )
        .order_by(PaperCashLedger.created_at.desc(), PaperCashLedger.id.desc())
    ).all()
    return [PaperCashLedgerRead.model_validate(row) for row in rows]


@router.post("/orders/{order_id}/preview", response_model=OrderPreview)
def preview_order(
    order_id: UUID,
    payload: OrderPreviewRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_required)],
    service: Annotated[PaperOrderService, Depends(get_paper_order_service)],
) -> OrderPreview:
    started_at = datetime.now(UTC)
    _owned_order(db, user_id=cast(UUID, user.id), order_id=order_id)
    try:
        preview = service.preview(
            user_id=cast(UUID, user.id), order_id=order_id, draft=payload.draft
        )
        db.commit()
        _record_order_span(
            order_id=order_id,
            name="preview",
            started_at=started_at,
            attrs={"outcome": "success"},
        )
        return preview
    except PaperTradingError as exc:
        db.rollback()
        _record_order_span(
            order_id=order_id,
            name="preview",
            started_at=started_at,
            attrs={"outcome": "failure", "error_code": exc.code},
            error=exc.code,
        )
        raise _business_error(exc) from exc
    except Exception:
        db.rollback()
        raise


@router.post("/orders/{order_id}/confirm", response_model=PaperOrderRead)
def confirm_order(
    order_id: UUID,
    payload: OrderConfirmRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_required)],
    service: Annotated[PaperOrderService, Depends(get_paper_order_service)],
) -> PaperOrderRead:
    started_at = datetime.now(UTC)
    current = _owned_order(db, user_id=cast(UUID, user.id), order_id=order_id)
    idempotent_replay = current.status is not OrderStatus.AWAITING_CONFIRMATION
    try:
        order = service.confirm(
            user_id=cast(UUID, user.id),
            order_id=order_id,
            draft=payload.draft,
            client_request_id=payload.client_request_id,
        )
        snapshot = PaperOrderRead.model_validate(order)
        db.commit()
        span = _record_order_span(
            order_id=order_id,
            name="confirm",
            started_at=started_at,
            attrs={
                "idempotent_replay": idempotent_replay,
                "outcome": "success",
                "status": cast(OrderStatus, order.status).value,
            },
        )
        dispatch_match_order(cast(UUID, order.id), trace_parent_id=span.span_id)
        return snapshot
    except PaperTradingError as exc:
        db.rollback()
        _record_order_span(
            order_id=order_id,
            name="confirm",
            started_at=started_at,
            attrs={"outcome": "failure", "error_code": exc.code},
            error=exc.code,
        )
        raise _business_error(exc) from exc
    except Exception:
        db.rollback()
        raise


@router.post("/orders/{order_id}/cancel-preview", response_model=CancelPreviewRead)
def preview_cancel(
    order_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_required)],
) -> CancelPreviewRead:
    order = _owned_order(db, user_id=cast(UUID, user.id), order_id=order_id)
    if order.status not in {
        OrderStatus.QUEUED,
        OrderStatus.OPEN,
        OrderStatus.PARTIALLY_FILLED,
    }:
        raise _business_error(PaperTradingError("order_not_cancellable", "模拟订单当前不可撤销"))
    return CancelPreviewRead(
        order_id=cast(UUID, order.id),
        status=order.status,
        filled_quantity=int(order.filled_quantity),
        remaining_quantity=int(order.quantity) - int(order.filled_quantity),
        reserved_cash=cast(Decimal, order.reserved_cash),
        reserved_quantity=int(order.reserved_quantity),
    )


@router.post("/orders/{order_id}/cancel-confirm", response_model=PaperOrderRead)
def confirm_cancel(
    order_id: UUID,
    payload: ConfirmationRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_required)],
    service: Annotated[PaperOrderService, Depends(get_paper_order_service)],
) -> PaperOrderRead:
    started_at = datetime.now(UTC)
    _owned_order(db, user_id=cast(UUID, user.id), order_id=order_id)
    try:
        order = service.cancel_confirmed(
            user_id=cast(UUID, user.id),
            order_id=order_id,
            confirmation_id=payload.confirmation_id,
        )
        snapshot = PaperOrderRead.model_validate(order)
        db.commit()
        _record_order_span(
            order_id=order_id,
            name="cancel",
            started_at=started_at,
            attrs={"outcome": "success", "status": cast(OrderStatus, order.status).value},
        )
        return snapshot
    except PaperTradingError as exc:
        db.rollback()
        _record_order_span(
            order_id=order_id,
            name="cancel",
            started_at=started_at,
            attrs={"outcome": "failure", "error_code": exc.code},
            error=exc.code,
        )
        raise _business_error(exc) from exc
    except Exception:
        db.rollback()
        raise


@router.post("/account/reset-preview", response_model=ResetPreviewRead)
def preview_reset(
    payload: ResetPreviewRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_required)],
) -> ResetPreviewRead:
    account = _account_for_generation(db, user_id=cast(UUID, user.id), generation=None)
    return ResetPreviewRead(
        account_id=cast(UUID, account.id),
        generation=int(account.generation),
        current_initial_cash=cast(Decimal, account.initial_cash),
        replacement_initial_cash=payload.initial_cash,
    )


@router.post("/account/reset-confirm", response_model=PaperAccountRead)
def confirm_reset(
    payload: ResetConfirmRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_required)],
    service: Annotated[PaperOrderService, Depends(get_paper_order_service)],
) -> PaperAccountRead:
    started_at = datetime.now(UTC)
    try:
        account = service.reset_account_confirmed(
            user_id=cast(UUID, user.id),
            initial_cash=payload.initial_cash,
            session_id=payload.session_id,
            confirmation_id=payload.confirmation_id,
        )
        snapshot = PaperAccountRead.model_validate(account)
        db.commit()
        _record_system_span(
            name="reset",
            started_at=started_at,
            attrs={"outcome": "success"},
        )
        return snapshot
    except PaperTradingError as exc:
        db.rollback()
        # There may be no current account id on validation/lookup failures.
        raise _business_error(exc) from exc
    except Exception:
        db.rollback()
        raise
