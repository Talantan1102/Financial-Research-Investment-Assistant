"""Pure fold algorithm: trades → PositionState(决策 1 / spec § 3.1)。

无 DB / 无 ORM 依赖,可独立 unit test 全部 fold 场景。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.models.trade import TradeType


@dataclass(frozen=True)
class TradeInput:
    """fold 算法输入,刻意不直接吃 ORM Trade 以保持纯函数。"""

    type: TradeType
    quantity: int
    price: Decimal
    trade_date: date


@dataclass(frozen=True)
class PositionState:
    """fold 输出 — 跟 Position 表字段对齐(quote 字段不在 fold 范围内)。"""

    quantity: int
    avg_cost: Decimal
    total_cost: Decimal
    realized_pnl: Decimal


def recompute_position_from_trades(trades: Iterable[TradeInput]) -> PositionState:
    """对 (user_id, ts_code) 的 Trade 全集按 trade_date asc 跑 fold。

    Spec § 3.1 算法:
      initial / buy → total_cost += q*p; quantity += q; avg_cost = total/qty (if qty>0)
      sell          → realized_pnl += q*(p - avg_cost)
                     total_cost -= q*avg_cost
                     quantity -= q
                     avg_cost stays (sell 不改 avg_cost,清仓后保留最后非零值)

    返回的 avg_cost / total_cost / realized_pnl 都是 Decimal 精度。
    """
    sorted_trades = sorted(trades, key=lambda t: t.trade_date)
    quantity = 0
    total_cost = Decimal("0")
    avg_cost = Decimal("0")
    realized_pnl = Decimal("0")

    for tr in sorted_trades:
        if tr.type in (TradeType.INITIAL, TradeType.BUY):
            total_cost += Decimal(tr.quantity) * tr.price
            quantity += tr.quantity
            if quantity > 0:
                avg_cost = total_cost / Decimal(quantity)
        elif tr.type == TradeType.SELL:
            realized_pnl += Decimal(tr.quantity) * (tr.price - avg_cost)
            total_cost -= Decimal(tr.quantity) * avg_cost
            quantity -= tr.quantity
            # avg_cost 保留(spec § 2.2 — quantity=0 保留最后非零值)

    # 量化精度:avg_cost 4 位小数,其他 2 位
    return PositionState(
        quantity=quantity,
        avg_cost=avg_cost.quantize(Decimal("0.0001")),
        total_cost=total_cost.quantize(Decimal("0.01")),
        realized_pnl=realized_pnl.quantize(Decimal("0.01")),
    )
