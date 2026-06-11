"""get_portfolio_positions —— InProcessTool 读 state.user_id,异步查持仓并算市值/浮盈。"""

from __future__ import annotations

import pytest

from app.chatloop.portfolio_tool import GetPortfolioPositionsTool, PortfolioPositionsArgs


class _FakePos:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, _stmt):
        return _FakeResult(self._rows)


def _factory(rows):
    def make():
        return _FakeSession(rows)

    return make


class _State:
    user_id = "11111111-1111-1111-1111-111111111111"


@pytest.mark.asyncio
async def test_positions_serialized_with_market_value() -> None:
    rows = [
        _FakePos(
            ts_code="600519.SH", name="贵州茅台", quantity=100, avg_cost=1500,
            total_cost=150000, realized_pnl=0, last_quote_price=1700, is_silenced=False,
        )
    ]
    tool = GetPortfolioPositionsTool(session_factory=_factory(rows))
    out = await tool.run_with_state(PortfolioPositionsArgs(), state=_State())
    assert out["total_count"] == 1
    p = out["positions"][0]
    assert p["ts_code"] == "600519.SH"
    assert p["market_value"] == 170000.0  # 100 * 1700
    assert p["unrealized_pnl"] == 20000.0  # 170000 - 150000
    assert out["total_market_value"] == 170000.0


@pytest.mark.asyncio
async def test_positions_empty() -> None:
    tool = GetPortfolioPositionsTool(session_factory=_factory([]))
    out = await tool.run_with_state(PortfolioPositionsArgs(), state=_State())
    assert out["total_count"] == 0
    assert out["positions"] == []
