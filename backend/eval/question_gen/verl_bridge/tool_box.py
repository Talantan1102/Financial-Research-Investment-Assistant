"""ToolBox —— 构造并运行**真实后端工具**(D3 工具服务核心)。

承设计:verl rollout 经 HTTP 调本服务,跑的是生产同款工具(对齐)。本 smoke 装两件:
- `get_stock_daily`(`app.tools.get_stock_daily.GetStockDailyTool`):区间收盘序列
- `run_python`(`app.chatloop.code_interpreter_tool.CodeInterpreterTool`):沙箱算指标

只构造 smoke 需要的两件 + 最小依赖(tushare 服务 + SkillExecutor 沙箱),**不拉 HeavySingletons**
(PG/Milvus/memory/llm)。cache=None → 关 data_refs;数据内联回模型,模型把数字写进 run_python 算。
"""

from __future__ import annotations

import os
from typing import Any


class _StubState:
    """CodeInterpreterTool.run_with_state 仅在 data_refs 时读 state;本 smoke 不用 refs,给个占位。"""

    user_id = "verl-rollout"


class ToolBox:
    def __init__(
        self, *, tushare: Any, skills_root: str, workdir_root: str, timeout_s: int = 30
    ) -> None:
        from app.chatloop.code_interpreter_tool import CodeInterpreterTool
        from app.skills.executor_backend import SkillExecutorBackend
        from app.skills.skill_executor import SkillExecutor
        from app.tools.get_stock_daily import GetStockDailyTool

        os.makedirs(skills_root, exist_ok=True)
        os.makedirs(workdir_root, exist_ok=True)

        executor = SkillExecutor(skills_root=skills_root, workdir_root=workdir_root)
        tools = [
            GetStockDailyTool(tushare=tushare),
            CodeInterpreterTool(
                backend=SkillExecutorBackend(executor), cache=None, timeout_s=timeout_s
            ),
        ]
        self._tools = {t.name: t for t in tools}
        self._state = _StubState()

    def schemas(self) -> list[dict[str, Any]]:
        return [t.schema_for_llm() for t in self._tools.values()]

    async def exec(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        if tool_name not in self._tools:
            raise KeyError(tool_name)
        tool = self._tools[tool_name]
        validated = tool.args_schema.model_validate(args)
        # CodeInterpreterTool 是 run_with_state(args, state);普通数据工具是 run(args)
        run_with_state = getattr(tool, "run_with_state", None)
        if run_with_state is not None:
            return await run_with_state(validated, self._state)
        return await tool.run(validated)


__all__ = ["ToolBox"]
