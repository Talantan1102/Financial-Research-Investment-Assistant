"""TradeService — Trade write 入口,单事务保证 Trade ↔ Position 一致(决策 1)。

Spec ref: § 3.1 流程 + § 3.3 三态机 guard(本文件 create + delete + update)。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.position import Position
from app.models.trade import Trade, TradeType
from app.services.portfolio_exceptions import ExpiredDeletionError, ImmutableTradeError
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

        Note: SQL ORDER BY trade_date ASC, created_at ASC ensures same-day
        trades arrive at recompute_position_from_trades in deterministic order.
        The fold function re-sorts by trade_date (stable sort), so the
        same-day created_at order is preserved through the fold.
        """
        # NOTE: stable-sort coupling with portfolio_recompute.recompute_position_from_trades
        # — that fold function re-sorts by trade_date (stable). Keep these in sync if
        # either side changes its sort key.
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

    def delete(self, trade_id: str, *, user_id: str) -> None:
        """删除 trade 并重算 Position。超 24h 抛 ExpiredDeletionError(spec § 3.3)。

        user_id 必传 — 防止跨用户操作(spec § 3.3 implicit user-isolation)。
        Caller 负责 session.commit()。
        """
        trade = self._session.query(Trade).filter_by(id=trade_id, user_id=user_id).one()
        if datetime.utcnow() - cast(datetime, trade.created_at) > timedelta(hours=24):
            raise ExpiredDeletionError("超 24h 不可删,请录反向交易抵消")
        user_id = cast(str, trade.user_id)
        ts_code = cast(str, trade.ts_code)
        name = cast(str, trade.name)
        self._session.delete(trade)
        self._session.flush()
        self._recompute_position(user_id=user_id, ts_code=ts_code, name=name)

    _INITIAL_UPDATABLE = {"ts_code", "name", "quantity", "price", "trade_date", "note"}

    def update(self, trade_id: str, *, user_id: str, **fields: object) -> Trade:
        """修改 INITIAL trade 的字段并重算 Position(spec § 3.3 + § 5 场景 3/5)。

        user_id 必传 — 防止跨用户操作(spec § 3.3 implicit user-isolation)。
        非 INITIAL trade 无论时间早晚均抛 ImmutableTradeError。
        Caller 负责 session.commit()。
        """
        trade = self._session.query(Trade).filter_by(id=trade_id, user_id=user_id).one()
        if trade.type != TradeType.INITIAL:
            raise ImmutableTradeError("常规交易不可改字段,过 24h 也不可")

        unknown = set(fields.keys()) - self._INITIAL_UPDATABLE
        if unknown:
            raise ValueError(f"unknown fields for update: {unknown}")

        for k, v in fields.items():
            setattr(trade, k, v)
        self._session.flush()
        self._recompute_position(
            user_id=cast(str, trade.user_id),
            ts_code=cast(str, trade.ts_code),
            name=cast(str, trade.name),
        )
        return trade
