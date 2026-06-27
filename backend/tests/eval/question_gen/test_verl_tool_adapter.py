"""verl_tool_adapter 单测:把后端 app.tools.Tool 包成 verl BaseTool,名字/schema/run 全等生产。

设计锚:docs/superpowers/specs/2026-06-25-d3-verl-tool-runtime-bridge-design.md。
不依赖 verl(桩基类)、不依赖真后端工具(注入假 Tool)。
"""

import asyncio

from eval.question_gen.verl_tool_adapter import VerlBackendToolAdapter
from pydantic import BaseModel


class _Args(BaseModel):
    ts_code: str
    start_date: str
    end_date: str


class _FakeBackendTool:
    """最小后端 Tool 替身:接口同 app.tools.base.Tool(name/args_schema/run/schema_for_llm)。"""

    name = "get_index_daily"
    args_schema = _Args

    def __init__(self):
        self.calls = []

    def schema_for_llm(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "取指数日线",
                "parameters": {"type": "object"},
            },
        }

    async def run(self, args: BaseModel) -> dict:
        self.calls.append(args)
        return {"rows": [{"trade_date": "20260612", "close": 28.45}]}


def test_adapter_exposes_backend_name_and_schema():
    bt = _FakeBackendTool()
    tool = VerlBackendToolAdapter(backend_tool=bt)
    # verl 看到的 schema/名字 == 生产工具的(对齐核心)
    assert tool.get_openai_tool_schema()["function"]["name"] == "get_index_daily"


def test_adapter_delegates_run_with_args_schema():
    bt = _FakeBackendTool()
    tool = VerlBackendToolAdapter(backend_tool=bt)
    iid, _ = asyncio.run(tool.create(create_kwargs={}))
    resp, tool_reward, _ = asyncio.run(
        tool.execute(
            iid, {"ts_code": "000938.SZ", "start_date": "20260312", "end_date": "20260612"}
        )
    )
    # 用后端 args_schema 校验后调真实 run();结果回文本;工具不给 reward
    assert isinstance(bt.calls[0], _Args) and bt.calls[0].ts_code == "000938.SZ"
    assert "28.45" in resp.text and tool_reward == 0.0


def test_adapter_reports_validation_error_not_crash():
    bt = _FakeBackendTool()
    tool = VerlBackendToolAdapter(backend_tool=bt)
    iid, _ = asyncio.run(tool.create(create_kwargs={}))
    resp, _, _ = asyncio.run(tool.execute(iid, {"ts_code": "x"}))  # 缺必填 → 校验错
    assert "error" in resp.text.lower() or "错误" in resp.text
