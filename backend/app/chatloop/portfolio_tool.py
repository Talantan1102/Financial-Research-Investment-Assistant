"""GetPortfolioPositionsTool — name="get_portfolio_positions"(解锁持仓饼图/treemap)。

InProcessTool:user_id 从 state.user_id 取(不让模型传/伪造),异步查 positions 表。
返回每个持仓的数量/成本/已实现损益 + 现价 + 市值 + 浮盈(市值/占比图直接可用)。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select

from app.chatloop.inprocess import InProcessTool
from app.chatloop.state import ChatLoopState


class PortfolioPositionsArgs(BaseModel):
    include_silenced: bool = False  # 默认不含静默仓位


def _f(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class GetPortfolioPositionsTool(InProcessTool):
    name = "get_portfolio_positions"
    description = "查用户当前持仓(股数/成本/市值/浮盈)。问'我的持仓/仓位'或要画持仓占比图时用。"
    args_schema = PortfolioPositionsArgs

    def __init__(self, *, session_factory: Any) -> None:
        self._session_factory = session_factory

    async def run_with_state(self, args: BaseModel, state: ChatLoopState) -> dict[str, Any]:
        args = PortfolioPositionsArgs.model_validate(args.model_dump())
        from app.models.position import Position  # noqa: PLC0415 — 避免 import-time DB 依赖

        user_id = UUID(state.user_id)
        async with self._session_factory() as sess:
            stmt = select(Position).where(Position.user_id == user_id)
            if not args.include_silenced:
                stmt = stmt.where(Position.is_silenced.is_(False))
            rows = (await sess.execute(stmt)).scalars().all()

        positions = []
        for p in rows:
            qty = int(p.quantity or 0)
            price = _f(p.last_quote_price)
            total_cost = _f(p.total_cost) or 0.0
            market_value = round(qty * price, 2) if price is not None else None
            unrealized = round(market_value - total_cost, 2) if market_value is not None else None
            positions.append(
                {
                    "ts_code": p.ts_code,
                    "name": p.name,
                    "quantity": qty,
                    "avg_cost": _f(p.avg_cost),
                    "total_cost": total_cost,
                    "realized_pnl": _f(p.realized_pnl),
                    "last_quote_price": price,
                    "market_value": market_value,
                    "unrealized_pnl": unrealized,
                }
            )

        total_mv = round(sum(p["market_value"] for p in positions if p["market_value"]), 2)
        return {"total_count": len(positions), "total_market_value": total_mv, "positions": positions}


__all__ = ["PortfolioPositionsArgs", "GetPortfolioPositionsTool"]
