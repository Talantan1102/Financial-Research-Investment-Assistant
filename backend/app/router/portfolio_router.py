"""Portfolio router — v1.0 持仓监控 REST API(Trade CRUD + Position read + Onboarding)。

Endpoints:
  POST   /portfolio/trades        — 单笔 trade 录入(initial / buy / sell)
  DELETE /portfolio/trades/{id}   — 24h 内删除(spec § 3.3)
  PATCH  /portfolio/trades/{id}   — initial trade 字段更新
  GET    /portfolio/positions     — 当前 user 的全部 positions(Task 11)
  POST   /portfolio/onboarding    — 批量录入 initial trades(Task 11)

Auth: get_current_user_required(JWT,跟 reports.py 同模式)。
错误:PortfolioError 子类映射到 409 Conflict。

注意:使用 async def 避免 anyio 将 sync 端点放入 threadpool,
保证测试 / 生产中 SQLAlchemy Session 的 same-thread 约束不被违反。
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.trade import TradeType
from app.models.user import User
from app.router.auth_router import get_current_user_required
from app.schemas.portfolio import (
    OnboardingRequest,
    OnboardingResponse,
    PositionRead,
    TradeCreate,
    TradeRead,
    TradeUpdate,
)
from app.services.portfolio_exceptions import (
    ExpiredDeletionError,
    ImmutableTradeError,
    PortfolioError,
)
from app.services.position_service import PositionService
from app.services.trade_service import TradeService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/portfolio", tags=["portfolio-v1.0"])


@router.post(
    "/trades",
    response_model=TradeRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_trade(
    payload: TradeCreate,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_required)],
) -> TradeRead:
    svc = TradeService(db)
    try:
        trade = svc.create(
            user_id=str(user.id),  # type: ignore[arg-type]
            ts_code=payload.ts_code,
            name=payload.name,
            ttype=TradeType(payload.type),
            quantity=payload.quantity,
            price=payload.price,
            trade_date=payload.trade_date,
            note=payload.note,
        )
        db.commit()
        db.refresh(trade)
        return TradeRead.model_validate(trade)
    except PortfolioError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.delete(
    "/trades/{trade_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_trade(
    trade_id: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_required)],
) -> None:
    svc = TradeService(db)
    try:
        svc.delete(trade_id, user_id=str(user.id))  # type: ignore[arg-type]
        db.commit()
    except NoResultFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trade not found")
    except ExpiredDeletionError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.patch("/trades/{trade_id}", response_model=TradeRead)
async def update_trade(
    trade_id: str,
    payload: TradeUpdate,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_required)],
) -> TradeRead:
    svc = TradeService(db)
    fields = payload.model_dump(exclude_unset=True)
    try:
        trade = svc.update(trade_id, user_id=str(user.id), **fields)  # type: ignore[arg-type]
        db.commit()
        db.refresh(trade)
        return TradeRead.model_validate(trade)
    except NoResultFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trade not found")
    except ImmutableTradeError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/positions", response_model=list[PositionRead])
async def list_positions(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_required)],
) -> list[PositionRead]:
    svc = PositionService(db)
    positions = svc.list_for_user(str(user.id))  # type: ignore[arg-type]
    return [PositionRead.model_validate(p) for p in positions]


@router.post(
    "/onboarding",
    response_model=OnboardingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def onboarding(
    payload: OnboardingRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_required)],
) -> OnboardingResponse:
    """雪球做法:批量录入 INITIAL trade,all-or-nothing 单事务。"""
    # 严格只接受 initial type(雪球语义)
    for tc in payload.trades:
        if tc.type != "initial":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="onboarding 仅接受 type='initial' trades",
            )

    trade_svc = TradeService(db)
    pos_svc = PositionService(db)
    created_trades = []
    for tc in payload.trades:
        trade = trade_svc.create(
            user_id=str(user.id),  # type: ignore[arg-type]
            ts_code=tc.ts_code,
            name=tc.name,
            ttype=TradeType(tc.type),
            quantity=tc.quantity,
            price=tc.price,
            trade_date=tc.trade_date,
            note=tc.note,
        )
        created_trades.append(trade)
    db.commit()
    for t in created_trades:
        db.refresh(t)

    positions = pos_svc.list_for_user(str(user.id))  # type: ignore[arg-type]
    return OnboardingResponse(
        trades=[TradeRead.model_validate(t) for t in created_trades],
        positions=[PositionRead.model_validate(p) for p in positions],
    )
