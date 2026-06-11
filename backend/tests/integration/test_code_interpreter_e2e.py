"""代码解释器端到端:真 subprocess + 真 plotly figure 往返。"""

from __future__ import annotations

from pathlib import Path

import pytest
from app.chatloop.code_interpreter_tool import CodeInterpreterArgs, CodeInterpreterTool
from app.skills.executor_backend import SkillExecutorBackend
from app.skills.skill_executor import SkillExecutor

pytest.importorskip("plotly")  # 未装 code-interpreter extra 则跳过


@pytest.mark.asyncio
async def test_run_python_produces_plotly_figure(tmp_path: Path) -> None:
    executor = SkillExecutor(skills_root=tmp_path / "s", workdir_root=tmp_path / "wd")
    tool = CodeInterpreterTool(backend=SkillExecutorBackend(executor))
    code = (
        "import sys, json\n"
        "import plotly.express as px\n"
        "d = json.load(sys.stdin)\n"
        "fig = px.line(x=d['x'], y=d['y'])\n"
        "print(json.dumps({'result': {'n': len(d['x'])}, 'figures': [fig.to_dict()]}))\n"
    )
    out = await tool.run_with_state(
        CodeInterpreterArgs(code=code, data={"x": [1, 2, 3], "y": [4, 5, 6]}),
        state=None,  # type: ignore[arg-type]
    )
    assert out["result"] == {"n": 3}
    assert len(out["figures"]) == 1
    fig = out["figures"][0]
    assert "data" in fig and "layout" in fig  # plotly figure 形状


@pytest.mark.asyncio
async def test_run_python_network_banned(tmp_path: Path) -> None:
    executor = SkillExecutor(skills_root=tmp_path / "s", workdir_root=tmp_path / "wd")
    tool = CodeInterpreterTool(backend=SkillExecutorBackend(executor))
    from app.tools.base import ToolError

    with pytest.raises(ToolError):
        await tool.run_with_state(
            CodeInterpreterArgs(code="import requests; requests.get('http://x')"),
            state=None,  # type: ignore[arg-type]
        )
