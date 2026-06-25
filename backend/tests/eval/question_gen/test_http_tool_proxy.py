"""HttpToolProxy 集成测试:用 httpx ASGITransport 在进程内连真工具服务,验 create/execute/release。"""
import httpx
import pandas as pd
import pytest

from eval.question_gen.verl_bridge.http_tool_proxy import HttpToolProxy
from eval.question_gen.verl_bridge.tool_server import build_app


class _FakeTushare:
    async def get_daily(self, *, ts_code, start, end):
        return pd.DataFrame(
            [{"trade_date": "20260312", "close": 30.0}, {"trade_date": "20260612", "close": 28.45}]
        )


def _proxy(tmp_path, tool_name):
    app = build_app(tushare=_FakeTushare(), skills_root=str(tmp_path / "s"), workdir_root=str(tmp_path / "w"))
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    schema = {"type": "function", "function": {"name": tool_name, "parameters": {}}}
    return HttpToolProxy({"server_url": "http://t", "tool_name": tool_name, "_client": client}, schema)


@pytest.mark.asyncio
async def test_proxy_data_tool_roundtrip(tmp_path):
    p = _proxy(tmp_path, "get_stock_daily")
    iid, _ = await p.create("r1")
    resp, reward, _ = await p.execute(iid, {"ts_code": "000938.SZ", "start_date": "20260312", "end_date": "20260612"})
    assert "28.45" in resp.text and reward == 0.0
    await p.release(iid)


@pytest.mark.asyncio
async def test_proxy_run_python_roundtrip(tmp_path):
    p = _proxy(tmp_path, "run_python")
    iid, _ = await p.create("r1")
    resp, _, _ = await p.execute(iid, {"code": "result = (28.45/30 - 1) * 100"})
    assert "-5.16" in resp.text
    await p.release(iid)


@pytest.mark.asyncio
async def test_proxy_surfaces_tool_error_as_text(tmp_path):
    p = _proxy(tmp_path, "run_python")
    iid, _ = await p.create("r1")
    resp, _, _ = await p.execute(iid, {"code": "1/0"})
    assert "tool error" in resp.text.lower()
