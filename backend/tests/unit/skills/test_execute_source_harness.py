"""execute_source wrapper harness —— 自动捕获 + 套主题 + data 注入 + 三重兜底(spec § 3)。

真子进程 + 真 plotly(没装 code-interpreter extra 则跳 plotly 用例)。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from app.skills.skill_executor import SkillExecutor


@pytest.fixture
def executor(tmp_path: Path) -> SkillExecutor:
    return SkillExecutor(skills_root=tmp_path / "s", workdir_root=tmp_path / "wd")


@pytest.mark.asyncio
async def test_data_injected_as_namespace_var(executor: SkillExecutor) -> None:
    # 模型不用读 stdin —— data 直接是命名空间变量
    res = await executor.execute_source(
        source="result = data['x'] + data['y']", payload={"x": 1, "y": 2}
    )
    assert res.ok is True
    assert res.stdout_json is not None
    assert res.stdout_json["result"] == 3
    assert res.stdout_json["figures"] == []


@pytest.mark.asyncio
async def test_user_print_does_not_break_contract(executor: SkillExecutor) -> None:
    # 用户 print 调试 → 被吞,不污染契约 JSON
    res = await executor.execute_source(source="print('debugging...'); result = 42", payload={})
    assert res.ok is True
    assert res.stdout_json is not None
    assert res.stdout_json["result"] == 42
    assert "debugging" in res.stdout_json.get("stdout", "")


@pytest.mark.asyncio
async def test_safety_scan_still_blocks_open(executor: SkillExecutor) -> None:
    res = await executor.execute_source(source="open('/etc/passwd')", payload={})
    assert res.ok is False
    assert res.error is not None
    assert res.error.kind == "safety_scan_rejected"


# --- plotly 相关(需 code-interpreter extra)------------------------------------

plotly = pytest.importorskip("plotly")


@pytest.mark.asyncio
async def test_assign_fig_captured_and_themed(executor: SkillExecutor) -> None:
    # 只赋 fig,不 print —— harness 抓取并序列化,且套了 ios 主题
    code = (
        "import plotly.graph_objects as go\n"
        "fig = go.Figure()\n"
        "fig.add_bar(x=data['names'], y=data['vals'])\n"
        "result = '已画'\n"
    )
    res = await executor.execute_source(source=code, payload={"names": ["A", "B"], "vals": [3, 5]})
    assert res.ok is True, res.error
    assert res.stdout_json is not None
    figs = res.stdout_json["figures"]
    assert len(figs) == 1
    assert "data" in figs[0] and "layout" in figs[0]
    # 套了 ios 模板 → layout.template 非空(plotly 把默认模板内联进 to_dict)
    assert figs[0]["layout"].get("template")
    assert res.stdout_json["result"] == "已画"


@pytest.mark.asyncio
async def test_assign_figures_list(executor: SkillExecutor) -> None:
    code = (
        "import plotly.graph_objects as go\n"
        "figures = [go.Figure(go.Scatter(y=[1,2,3])), go.Figure(go.Bar(y=[4,5,6]))]\n"
    )
    res = await executor.execute_source(source=code, payload={})
    assert res.ok is True, res.error
    assert res.stdout_json is not None
    assert len(res.stdout_json["figures"]) == 2


@pytest.mark.asyncio
async def test_legacy_print_json_fallback(executor: SkillExecutor) -> None:
    # 旧式契约:不赋变量,直接 print(json.dumps({figures:[fig.to_dict()]})) → 兜底解析
    code = (
        "import json, plotly.graph_objects as go\n"
        "f = go.Figure(go.Scatter(y=[1,2,3]))\n"
        "print(json.dumps({'result': 'legacy', 'figures': [f.to_dict()]}))\n"
    )
    res = await executor.execute_source(source=code, payload={})
    assert res.ok is True, res.error
    assert res.stdout_json is not None
    assert len(res.stdout_json["figures"]) == 1
    assert res.stdout_json["result"] == "legacy"
