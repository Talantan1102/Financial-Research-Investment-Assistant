"""trade_cal MCP 工具单测(mock 模式,确定性历法)。"""

from __future__ import annotations

import json

import pytest
from app.mcp_server.tools.trade_cal import handle


async def _call(args: dict) -> dict:
    out = await handle(args)
    return json.loads(out[0].text)


@pytest.fixture(autouse=True)
def _mock_mode(monkeypatch):
    monkeypatch.setenv("TUSHARE_MODE", "mock")


@pytest.mark.asyncio
async def test_is_open_weekend():
    r = await _call({"action": "is_open", "date": "20260614"})  # 周日
    assert r["is_open"] is False


@pytest.mark.asyncio
async def test_is_open_trading_day():
    r = await _call({"action": "is_open", "date": "20260612"})  # 周五,开市
    assert r["is_open"] is True


@pytest.mark.asyncio
async def test_latest_from_sunday():
    r = await _call({"action": "latest", "date": "20260614"})  # 周日
    assert r["result_date"] == "20260612"  # 上一个周五
    assert r["is_open_on_query"] is False


@pytest.mark.asyncio
async def test_prev_and_next():
    assert (await _call({"action": "prev", "date": "20260615"}))["result_date"] == "20260612"
    assert (await _call({"action": "next", "date": "20260612"}))["result_date"] == "20260615"


@pytest.mark.asyncio
async def test_count_and_list():
    c = await _call({"action": "count", "start": "20260601", "end": "20260607"})
    assert c["count"] == 5  # 周一到周日里 5 个交易日(无节假日)
    lst = await _call({"action": "list", "start": "20260601", "end": "20260607"})
    assert lst["count"] == 5
    assert len(lst["dates"]) == 5
    assert lst["truncated"] is False


@pytest.mark.asyncio
async def test_missing_param_guidance():
    r = await _call({"action": "latest"})  # 缺 date
    assert "参数校验失败" in r.get("error", "")
    r2 = await _call({"action": "count", "start": "20260101"})  # 缺 end
    assert "参数校验失败" in r2.get("error", "")


@pytest.mark.asyncio
async def test_bad_action():
    r = await _call({"action": "nope"})
    assert "参数校验失败" in r.get("error", "")
