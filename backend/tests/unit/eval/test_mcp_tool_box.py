"""McpToolBox 单测(verl 工具面对齐 MCP)—— 不连网/不连重服务。

覆盖验收:AC1 界面=SFT 同款分组工具名;AC4 stub 不崩;search_tools 纯函数;未知工具。
AC2/AC3(真 tushare 数据 + 并发 as_of 隔离)走 live 脚本验证,不在此(需网络)。
"""

import tempfile

import pytest
from app.tools.base import ToolError
from eval.question_gen.verl_bridge.mcp_tool_box import McpToolBox


@pytest.fixture
def box():
    return McpToolBox(skills_root=tempfile.mkdtemp(), workdir_root=tempfile.mkdtemp())


def test_schemas_match_sft_surface(box):
    """AC1:工具名集 == SFT 采轨用过的分组工具;旧原子名不再出现。"""
    names = {s["function"]["name"] for s in box.schemas()}
    for n in [
        "get_financial_statements",
        "get_market_indicators",
        "get_daily",
        "get_stock_quote",
        "compare_stocks",
        "trade_cal",
        "run_python",
        "search_tools",
    ]:
        assert n in names, f"缺 SFT 同款工具 {n}"
    # 已从原子对齐到分组:旧原子名不应再暴露
    assert "get_financials" not in names
    assert "get_daily_basic" not in names


@pytest.mark.asyncio
async def test_stub_returns_note_no_crash(box):
    """AC4:重依赖工具 stub 占位,不抛、不连 Milvus/PG/Bocha。"""
    for t in ["memory_search", "kb_search", "web_search", "get_news", "get_portfolio_positions"]:
        r = await box.exec(t, {"query": "x"}, as_of="20260612")
        assert "note" in r


@pytest.mark.asyncio
async def test_search_tools_pure(box):
    """search_tools 走纯函数 search_docs,返 {"docs":[{name,doc}]}。"""
    r = await box.exec("search_tools", {"query": "股价 历史 波动"}, as_of="20260612")
    assert "docs" in r and isinstance(r["docs"], list)
    if r["docs"]:
        assert {"name", "doc"} <= set(r["docs"][0].keys())


@pytest.mark.asyncio
async def test_search_tools_requires_query(box):
    with pytest.raises(ToolError):
        await box.exec("search_tools", {}, as_of="20260612")


@pytest.mark.asyncio
async def test_unknown_tool_keyerror(box):
    with pytest.raises(KeyError):
        await box.exec("no_such_tool_xyz", {}, as_of="20260612")
