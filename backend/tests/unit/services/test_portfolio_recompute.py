"""recompute_position_from_trades fold 算法测试 (纯函数,无 DB)。

Spec ref: docs/superpowers/specs/2026-05-07-v1.0-portfolio-data-model-engineering-design.md
§ 3.1 fold 算法 + § 5 测试场景。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.models.trade import TradeType
from app.services.portfolio_recompute import (
    TradeInput,
    recompute_position_from_trades,
)


def _t(ttype: TradeType, qty: int, price: str, ymd: tuple[int, int, int]) -> TradeInput:
    return TradeInput(
        type=ttype,
        quantity=qty,
        price=Decimal(price),
        trade_date=date(*ymd),
    )


# ---- Spec § 5 测试场景 1:基本聚合 ------------------------------------------


def test_basic_aggregate_initial_buy_sell() -> None:
    """initial 200@1450 → buy 50@1500 → sell 30@1600。

    fold 推算(spec § 5 场景 1):
      after initial: qty=200, total=290000, avg=1450
      after buy:     qty=250, total=365000, avg=1460
      after sell:    realized += 30*(1600-1460)=4200, total -= 30*1460=43800
      → qty=220, total=321200, avg=1460(321200/220=1460), realized=4200
    """
    trades = [
        _t(TradeType.INITIAL, 200, "1450.00", (2024, 6, 1)),
        _t(TradeType.BUY, 50, "1500.00", (2026, 1, 15)),
        _t(TradeType.SELL, 30, "1600.00", (2026, 4, 20)),
    ]
    state = recompute_position_from_trades(trades)
    assert state.quantity == 220
    assert state.avg_cost == Decimal("1460.0000")
    assert state.total_cost == Decimal("321200.00")
    assert state.realized_pnl == Decimal("4200.00")


def test_delete_buy_reverses_position() -> None:
    """删上面的 buy 后,fold 序列变 initial 200@1450 → sell 30@1600。

    fold 推算(spec § 5 场景 2):
      after initial: qty=200, total=290000, avg=1450
      after sell:    realized += 30*(1600-1450)=4500, total -= 30*1450=43500
      → qty=170, total=246500, avg=1450, realized=4500
    """
    trades = [
        _t(TradeType.INITIAL, 200, "1450.00", (2024, 6, 1)),
        _t(TradeType.SELL, 30, "1600.00", (2026, 4, 20)),
    ]
    state = recompute_position_from_trades(trades)
    assert state.quantity == 170
    assert state.avg_cost == Decimal("1450.0000")
    assert state.total_cost == Decimal("246500.00")
    assert state.realized_pnl == Decimal("4500.00")


def test_clear_then_rebuy_keeps_realized_pnl() -> None:
    """initial 100@1500 → sell 100@1600 → buy 50@1400。

    fold:
      after initial: qty=100, total=150000, avg=1500
      after sell 100: realized += 100*(1600-1500)=10000, total -= 100*1500=150000
                     → qty=0, total=0, avg=1500(保留最后非零值), realized=10000
      after buy 50: qty=50, total=50*1400=70000, avg=70000/50=1400
                    realized 不动(只 buy 不动 realized)
    """
    trades = [
        _t(TradeType.INITIAL, 100, "1500.00", (2024, 6, 1)),
        _t(TradeType.SELL, 100, "1600.00", (2026, 1, 15)),
        _t(TradeType.BUY, 50, "1400.00", (2026, 4, 1)),
    ]
    state = recompute_position_from_trades(trades)
    assert state.quantity == 50
    assert state.avg_cost == Decimal("1400.0000")
    assert state.total_cost == Decimal("70000.00")
    assert state.realized_pnl == Decimal("10000.00")


def test_empty_trades_returns_zeros() -> None:
    state = recompute_position_from_trades([])
    assert state.quantity == 0
    assert state.avg_cost == Decimal("0.0000")
    assert state.total_cost == Decimal("0.00")
    assert state.realized_pnl == Decimal("0.00")


def test_unsorted_trades_get_sorted_before_fold() -> None:
    """乱序输入应按 trade_date asc 排序后 fold,结果跟 Step 1 一致。"""
    trades = [
        _t(TradeType.SELL, 30, "1600.00", (2026, 4, 20)),  # 最后一笔放最前
        _t(TradeType.INITIAL, 200, "1450.00", (2024, 6, 1)),
        _t(TradeType.BUY, 50, "1500.00", (2026, 1, 15)),
    ]
    state = recompute_position_from_trades(trades)
    assert state.quantity == 220
    assert state.avg_cost == Decimal("1460.0000")
    assert state.total_cost == Decimal("321200.00")
    assert state.realized_pnl == Decimal("4200.00")
