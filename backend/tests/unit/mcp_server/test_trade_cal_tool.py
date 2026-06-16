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


@pytest.mark.asyncio
async def test_malformed_date_guidance():
    # 带分隔符 / 非数字日期 → 指导性错误,不抛未捕获 ValueError
    r = await _call({"action": "is_open", "date": "2026-06-15"})
    assert "参数校验失败" in r.get("error", "")
    r2 = await _call({"action": "count", "start": "abc", "end": "20260101"})
    assert "参数校验失败" in r2.get("error", "")


def test_parse_lookback_valid():
    from app.mcp_server.tools.trade_cal import _parse_lookback

    assert _parse_lookback("1y") == ("y", 1)
    assert _parse_lookback("6m") == ("m", 6)
    assert _parse_lookback("30d") == ("d", 30)
    assert _parse_lookback("20td") == ("td", 20)
    assert _parse_lookback("ytd") == ("ytd", 0)


def test_parse_lookback_invalid():
    from app.mcp_server.tools.trade_cal import _parse_lookback

    for bad in ["", "0y", "abc", "y", "1ytd", "-3m", None]:
        with pytest.raises(ValueError):
            _parse_lookback(bad)


def test_minus_months_and_years_clamp():
    from app.mcp_server.tools.trade_cal import _minus_months, _minus_years

    assert _minus_years("20260616", 1) == "20250616"
    assert _minus_years("20240229", 1) == "20230228"  # 闰日夹到 2/28
    assert _minus_months("20260616", 6) == "20251216"
    assert _minus_months("20260331", 1) == "20260228"  # 日溢出夹到月末(2026 非闰)


@pytest.mark.asyncio
async def test_window_1y():
    r = await _call({"action": "window", "anchor": "20260616", "lookback": "1y"})
    assert r["start"] == "20250616"
    assert r["end"] == "20260616"
    assert r["anchor_is_open"] is True
    c = await _call({"action": "count", "start": "20250616", "end": "20260616"})
    assert r["trading_days"] == c["count"]


@pytest.mark.asyncio
async def test_window_ytd_snaps_forward_past_holiday():
    r = await _call({"action": "window", "anchor": "20260616", "lookback": "ytd"})
    assert r["start"] == "20260105"  # 0101/0102 元旦休 + 周末 → 顺延到 1/5
    assert r["end"] == "20260616"


@pytest.mark.asyncio
async def test_window_n_trading_days():
    r = await _call({"action": "window", "anchor": "20260616", "lookback": "20td"})
    assert r["trading_days"] == 20
    assert r["end"] == "20260616"
    assert r["start"] == "20260520"
    c = await _call({"action": "count", "start": r["start"], "end": r["end"]})
    assert c["count"] == 20


@pytest.mark.asyncio
async def test_window_anchor_on_weekend():
    r = await _call({"action": "window", "anchor": "20260620", "lookback": "1y"})  # 6/20 周六
    assert r["anchor_is_open"] is False
    assert r["end"] == "20260618"  # 6/19 端午休、6/20 周六 → 最近交易日 6/18


@pytest.mark.asyncio
async def test_window_bad_lookback():
    r = await _call({"action": "window", "anchor": "20260616", "lookback": "xy"})
    assert "参数校验失败" in r.get("error", "")


@pytest.mark.asyncio
async def test_window_missing_anchor():
    r = await _call({"action": "window", "lookback": "1y"})
    assert "参数校验失败" in r.get("error", "")
