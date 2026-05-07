"""TradeService — Trade write 入口,单事务保证 Trade ↔ Position 一致(决策 1)。

Spec ref: § 3.1 流程 + § 3.3 三态机 guard(本文件 create + delete + update)。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import cast
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.position import Position
from app.models.trade import Trade, TradeType
from app.services.portfolio_recompute import (
    TradeInput,
    recompute_position_from_trades,
)


class TradeService:
    """Trade CRUD + 同事务 Position recompute。

    所有 write 路径(create / delete / update)在调用方提交前都同事务 UPSERT Position。
    Caller 负责 session.commit(),本类只 add / flush / merge。
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        user_id: str,
        ts_code: str,
        name: str,
        ttype: TradeType,
        quantity: int,
        price: Decimal,
        trade_date: date,
        note: str | None = None,
    ) -> Trade:
        trade = Trade(
            id=str(uuid4()),
            user_id=user_id,
            ts_code=ts_code,
            name=name,
            type=ttype,
            quantity=quantity,
            price=price,
            trade_date=trade_date,
            note=note,
        )
        self._session.add(trade)
        self._session.flush()
        self._recompute_position(user_id=user_id, ts_code=ts_code, name=name)
        return trade

    def _recompute_position(self, *, user_id: str, ts_code: str, name: str) -> None:
        """fold 该 (user_id, ts_code) 全部 Trade → UPSERT Position 行。

        SQL ORDER BY trade_date ASC, created_at ASC for deterministic
        same-day trade ordering (fold algorithm relies on caller-provided ordering).
        """
        trades = (
            self._session.query(Trade)
            .filter_by(user_id=user_id, ts_code=ts_code)
            .order_by(Trade.trade_date.asc(), Trade.created_at.asc())
            .all()
        )
        inputs = [
            TradeInput(
                type=cast(TradeType, t.type),
                quantity=cast(int, t.quantity),
                price=cast(Decimal, t.price),
                trade_date=cast(date, t.trade_date),
            )
            for t in trades
        ]
        state = recompute_position_from_trades(inputs)

        pos = (
            self._session.query(Position).filter_by(user_id=user_id, ts_code=ts_code).one_or_none()
        )
        if pos is None:
            pos = Position(
                id=str(uuid4()),
                user_id=user_id,
                ts_code=ts_code,
                name=name,
                quantity=state.quantity,
                avg_cost=state.avg_cost,
                total_cost=state.total_cost,
                realized_pnl=state.realized_pnl,
            )
            self._session.add(pos)
        else:
            pos.quantity = state.quantity  # type: ignore[assignment]
            pos.avg_cost = state.avg_cost  # type: ignore[assignment]
            pos.total_cost = state.total_cost  # type: ignore[assignment]
            pos.realized_pnl = state.realized_pnl  # type: ignore[assignment]
            pos.name = name  # type: ignore[assignment]  # 同步名称变更
        self._session.flush()
