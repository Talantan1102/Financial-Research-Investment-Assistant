"""工具服务 HTTP 测试(TestClient):/tools、建会话、exec 数据工具+run_python、错误转可读。"""

import pandas as pd
from eval.question_gen.verl_bridge.tool_server import build_app
from fastapi.testclient import TestClient


class _FakeTushare:
    async def get_daily(self, *, ts_code, start, end):
        return pd.DataFrame(
            [{"trade_date": "20260312", "close": 30.0}, {"trade_date": "20260612", "close": 28.45}]
        )


def _client(tmp_path):
    app = build_app(
        tushare=_FakeTushare(), skills_root=str(tmp_path / "s"), workdir_root=str(tmp_path / "w")
    )
    return TestClient(app)


def test_list_tools(tmp_path):
    c = _client(tmp_path)
    names = {t["function"]["name"] for t in c.get("/tools").json()["tools"]}
    assert {"get_stock_daily", "run_python"} <= names


def test_session_exec_data_then_compute(tmp_path):
    c = _client(tmp_path)
    sid = c.post("/sessions").json()["session_id"]
    # 取数
    r1 = c.post(
        f"/sessions/{sid}/exec",
        json={
            "tool": "get_stock_daily",
            "args": {"ts_code": "000938.SZ", "start_date": "20260312", "end_date": "20260612"},
        },
    ).json()
    assert r1["ok"] and r1["result"]["closes"][-1]["close"] == 28.45
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
