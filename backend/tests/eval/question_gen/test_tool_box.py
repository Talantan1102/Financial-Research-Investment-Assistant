"""ToolBox 单测:建真实工具(get_stock_daily + run_python)、列 schema、跑工具。

数据工具注入假 tushare;run_python 走真沙箱(execute_source)。
"""

import pandas as pd
import pytest
from eval.question_gen.verl_bridge.tool_box import ToolBox


class _FakeTushare:
    async def get_daily(self, *, ts_code, start, end):
        return pd.DataFrame(
            [{"trade_date": "20260312", "close": 30.0}, {"trade_date": "20260612", "close": 28.45}]
        )


def _box(tmp_path):
    return ToolBox(
        tushare=_FakeTushare(), skills_root=str(tmp_path / "s"), workdir_root=str(tmp_path / "w")
    )


def test_schemas_has_both_tools(tmp_path):
    names = {s["function"]["name"] for s in _box(tmp_path).schemas()}
    assert {
        "get_stock_daily",
        "get_stock_quote",
        "get_financials",
        "get_daily_basic",
        "get_pe_history",
        "run_python",
    } <= names


@pytest.mark.asyncio
async def test_exec_data_tool_returns_closes(tmp_path):
    out = await _box(tmp_path).exec(
        "get_stock_daily",
        {"ts_code": "000938.SZ", "start_date": "20260312", "end_date": "20260612"},
    )
    assert out["closes"][0]["close"] == 30.0 and out["closes"][-1]["close"] == 28.45


@pytest.mark.asyncio
async def test_exec_run_python_computes(tmp_path):
    out = await _box(tmp_path).exec("run_python", {"code": "result = (28.45/30 - 1) * 100"})
    assert abs(out["result"] - (-5.1666666)) < 0.01


@pytest.mark.asyncio
async def test_exec_unknown_tool_raises(tmp_path):
    with pytest.raises(KeyError):
        await _box(tmp_path).exec("nope", {})
