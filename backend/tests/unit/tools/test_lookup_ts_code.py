"""LookupTsCodeTool 单测:股票名 → ts_code(薄包 TushareService.get_stock_basic)。"""
import pandas as pd
import pytest

from app.tools.base import ToolError
from app.tools.lookup_ts_code import LookupTsCodeArgs, LookupTsCodeTool


class _FakeTushare:
    async def get_stock_basic(self, *, ts_code=None):
        return pd.DataFrame([
            {"ts_code": "300558.SZ", "name": "贝达药业"},
            {"ts_code": "688506.SH", "name": "百利天恒"},
        ])


@pytest.mark.asyncio
async def test_exact_name_to_code():
    out = await LookupTsCodeTool(tushare=_FakeTushare()).run(LookupTsCodeArgs(name="贝达药业"))
    assert out["ts_code"] == "300558.SZ" and out["name"] == "贝达药业"


@pytest.mark.asyncio
async def test_not_found_raises():
    with pytest.raises(ToolError):
        await LookupTsCodeTool(tushare=_FakeTushare()).run(LookupTsCodeArgs(name="不存在公司"))
