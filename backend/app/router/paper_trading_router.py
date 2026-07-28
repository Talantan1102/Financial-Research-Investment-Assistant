"""Tenant-safe, read/preview-only REST surface for simulated trading."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, cast
from zoneinfo import ZoneInfo

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.paper_account import PaperAccount, PaperHoldingLot
from app.models.paper_order import OrderStatus, PaperOrder
from app.models.user import User
from app.router.auth_router import get_current_user_required
from app.schemas.paper_trading import (
    OrderDraftPreview,
    OrderPreviewRequest,
    PaperAccountRead,
    PaperHoldingRead,
    PaperOrderRead,
)
from app.services.paper_trading.account_service import PaperAccountService
from app.services.paper_trading.clock import TradingClock, TushareTradingCalendar
from app.services.paper_trading.errors import PaperTradingError
from app.services.paper_trading.order_service import PaperOrderService
from app.services.paper_trading.quote_provider import TushareRealtimeQuoteProvider
from app.services.paper_trading.rulebook import RuleBook
from app.services.tushare_factory import build_tushare_service

router = APIRouter(prefix="/api/v0/paper-trading", tags=["paper-trading"])

_INVALID_ORDER_CODES = {
    "invalid_order",
    "invalid_order_time",
    "invalid_price_tick",
    "price_out_of_bounds",
    "security_identity_mismatch",
    "unsupported_trading_regime",
}
_CONFLICT_CODES = {
    "insufficient_cash",
    "insufficient_market_depth",
    "insufficient_sellable_quantity",
    "stale_account_generation",
    "suspended_security",
}


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


def _user_id(user: User) -> uuid.UUID:
    return cast(uuid.UUID, user.id)


def _raise_safe_domain_error(exc: PaperTradingError) -> None:
    if exc.code in {"paper_account_not_found", "paper_order_not_found"}:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Paper trading resource not found",
        ) from exc
    if exc.code in _INVALID_ORDER_CODES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": exc.code, "message": "订单参数不符合交易规则"},
        ) from exc
    if exc.code in _CONFLICT_CODES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": exc.code, "message": "当前账户或市场状态不允许该操作"},
        ) from exc
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"code": exc.code, "message": "模拟交易请求无法处理"},
    ) from exc


@router.get("/account", response_model=PaperAccountRead)
def get_account(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_required)],
) -> PaperAccountRead:
    try:
        account = PaperAccountService(db).get_or_create(user_id=_user_id(user))
        db.commit()
        db.refresh(account)
        return PaperAccountRead.model_validate(account)
    except PaperTradingError as exc:
        db.rollback()
        _raise_safe_domain_error(exc)


@router.get("/holdings", response_model=list[PaperHoldingRead])
def list_holdings(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_required)],
    account_generation: Annotated[int | None, Query(ge=1)] = None,
) -> list[PaperHoldingRead]:
    """Read one user-owned account generation, including T+1 availability."""
    if account_generation is None:
        try:
            account = PaperAccountService(db).get_active(user_id=_user_id(user))
        except PaperTradingError as exc:
            _raise_safe_domain_error(exc)
    else:
        account = db.scalar(
            select(PaperAccount).where(
                PaperAccount.user_id == _user_id(user),
                PaperAccount.generation == account_generation,
            )
        )
        if account is None:
            return []

    lots = db.scalars(
        select(PaperHoldingLot)
        .where(
            PaperHoldingLot.account_id == account.id,
            PaperHoldingLot.generation == account.generation,
            PaperHoldingLot.remaining_quantity > 0,
        )
        .order_by(PaperHoldingLot.ts_code, PaperHoldingLot.created_at, PaperHoldingLot.id)
    ).all()
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    grouped: dict[str, dict[str, object]] = {}
    for lot in lots:
        ts_code = cast(str, lot.ts_code)
        item = grouped.setdefault(
            ts_code,
            {
                "generation": int(lot.generation),
                "ts_code": ts_code,
                "name": cast(str, lot.name),
                "quantity": 0,
                "frozen_quantity": 0,
                "sellable_quantity": 0,
                "cost": Decimal("0"),
            },
        )
        quantity = int(lot.remaining_quantity)
        frozen = int(lot.frozen_quantity)
        item["quantity"] = cast(int, item["quantity"]) + quantity
        item["frozen_quantity"] = cast(int, item["frozen_quantity"]) + frozen
        if lot.available_on <= today:
            item["sellable_quantity"] = cast(int, item["sellable_quantity"]) + quantity - frozen
        item["cost"] = cast(Decimal, item["cost"]) + cast(Decimal, lot.unit_cost) * quantity
    return [
        PaperHoldingRead.model_validate(
            {
                **item,
                "average_cost": cast(Decimal, item["cost"]) / cast(int, item["quantity"]),
            }
        )
        for item in grouped.values()
    ]


@router.get("/orders", response_model=list[PaperOrderRead])
def list_orders(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_required)],
    account_generation: Annotated[int | None, Query(ge=1)] = None,
    order_status: Annotated[OrderStatus | None, Query(alias="status")] = None,
    ts_code: Annotated[
        str | None,
        Query(min_length=9, max_length=9, pattern=r"^\d{6}\.(?:SH|SZ|BJ)$"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> list[PaperOrderRead]:
    statement = select(PaperOrder).where(PaperOrder.user_id == _user_id(user))
    if account_generation is not None:
        statement = statement.where(PaperOrder.account_generation == account_generation)
    if order_status is not None:
        statement = statement.where(PaperOrder.status == order_status)
    if ts_code is not None:
        statement = statement.where(PaperOrder.ts_code == ts_code)
    statement = statement.order_by(PaperOrder.created_at.desc(), PaperOrder.id.desc())
    rows = db.scalars(statement.offset(offset).limit(limit)).all()
    return [PaperOrderRead.model_validate(row) for row in rows]


@router.get("/orders/{order_id}", response_model=PaperOrderRead)
def get_order(
    order_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_required)],
) -> PaperOrderRead:
    order = db.scalar(
        select(PaperOrder).where(
            PaperOrder.id == order_id,
            PaperOrder.user_id == _user_id(user),
        )
    )
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Paper trading resource not found",
        )
    return PaperOrderRead.model_validate(order)


@router.post("/orders/preview", response_model=OrderDraftPreview)
def preview_order(
    payload: OrderPreviewRequest,
    user: Annotated[User, Depends(get_current_user_required)],
    service: Annotated[PaperOrderService, Depends(get_paper_order_service)],
) -> OrderDraftPreview:
    """Calculate a quote-backed preview without creating an order or reserving assets."""
    try:
        return service.preview_draft(
            user_id=_user_id(user),
            draft=payload.draft,
        )
    except PaperTradingError as exc:
        _raise_safe_domain_error(exc)
