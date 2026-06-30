"""工具服务 HTTP 测试(TestClient):/tools、建会话、exec 数据工具+run_python、错误转可读。"""

import pandas as pd
from eval.question_gen.verl_bridge.tool_server import build_app
from fastapi.testclient import TestClient


class _FakeTushare:
    async def get_daily(self, *, ts_code, start, end):
        return pd.DataFrame(
            [
                {"trade_date": "20260312", "open": 29.5, "high": 30.5, "low": 29.0, "close": 30.0},
                {"trade_date": "20260612", "open": 28.0, "high": 28.9, "low": 27.8, "close": 28.45},
            ]
        )


def _client(tmp_path):
    app = build_app(
        tushare=_FakeTushare(), skills_root=str(tmp_path / "s"), workdir_root=str(tmp_path / "w")
    )
    return TestClient(app)


def test_list_tools(tmp_path):
    c = _client(tmp_path)
    names = {t["function"]["name"] for t in c.get("/tools").json()["tools"]}
    assert {"get_daily", "run_python"} <= names


def test_session_exec_data_then_compute(tmp_path, monkeypatch):
    # McpToolBox 数据工具走 MCP handle → build_tushare_service() 工厂(不吃 build_app 注入的
    # tushare),故在工厂层注入 Fake,让 get_daily 取到确定数据。
    monkeypatch.setattr(
        "app.services.tushare_factory.build_tushare_service", lambda: _FakeTushare()
    )
    c = _client(tmp_path)
    sid = c.post("/sessions").json()["session_id"]
    # 取数(get_daily 列式返回:close 为数组)
    r1 = c.post(
        f"/sessions/{sid}/exec",
        json={
            "tool": "get_daily",
            "args": {"ts_code": "000938.SZ", "start": "20260312", "end": "20260612"},
        },
    ).json()
    assert r1["ok"] and r1["result"]["close"][-1] == 28.45
    # 算
    r2 = c.post(
        f"/sessions/{sid}/exec",
        json={"tool": "run_python", "args": {"code": "result = (28.45/30 - 1) * 100"}},
    ).json()
    assert r2["ok"] and abs(r2["result"]["result"] - (-5.16667)) < 0.01
    assert c.delete(f"/sessions/{sid}").json()["closed"]


def test_tool_error_is_readable_not_500(tmp_path):
    c = _client(tmp_path)
    sid = c.post("/sessions").json()["session_id"]
    r = c.post(f"/sessions/{sid}/exec", json={"tool": "run_python", "args": {"code": "1/0"}}).json()
    assert r["ok"] is False and "error" in r
