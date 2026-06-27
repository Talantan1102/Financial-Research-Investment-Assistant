# backend/eval/question_gen/verl_tool_adapter.py
"""通用适配器:把后端 app.tools.Tool 包成 verl BaseTool —— 训练工具 == 生产工具。

设计锚:docs/superpowers/specs/2026-06-25-d3-verl-tool-runtime-bridge-design.md。
verl rollout 看到的工具名/schema/run 行为完全等于后端生产工具,模型学会的 tool-calling
直接可用在真实系统(无 train/serve 漂移)。

适用:**无状态**后端工具(数据类,get_index_daily/get_stock_quote…)。run_python 等
有状态工具(ChatLoopState + data_refs + 沙箱)的桥接见设计文档 §"run_python",另行处理。

跨环境:verl BaseTool 仅训练环境可 import;verl 缺失时回退等价桩,便于 backend 环境单测。
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

try:  # 训练(verl)环境
    from verl.tools.base_tool import BaseTool
    from verl.tools.schemas import ToolResponse
except ImportError:  # backend/单测环境:等价桩

    class BaseTool:  # type: ignore[no-redef]
        def __init__(self, config: dict | None = None, tool_schema: Any = None) -> None:
            self.config = config
            self.tool_schema = tool_schema

    class ToolResponse:  # type: ignore[no-redef]
        def __init__(self, text: str = "") -> None:
            self.text = text


class VerlBackendToolAdapter(BaseTool):
    """包住一个后端 Tool 实例(.name / .args_schema / async run / schema_for_llm)。"""

    def __init__(self, backend_tool: Any, config: dict | None = None) -> None:
        # tool_schema 直接取后端工具的 schema_for_llm() —— 对齐核心
        super().__init__(config=config or {}, tool_schema=backend_tool.schema_for_llm())
        self._tool = backend_tool
        self._instances: dict[str, dict[str, Any]] = {}

    @property
    def name(self) -> str:
        return self._tool.name

    def get_openai_tool_schema(self) -> Any:
        return self._tool.schema_for_llm()

    async def create(
        self, instance_id: str | None = None, create_kwargs: dict | None = None, **kwargs: Any
    ) -> tuple[str, Any]:
        instance_id = instance_id or str(uuid4())
        self._instances[instance_id] = dict(create_kwargs or {})
        return instance_id, ToolResponse()

    async def execute(
        self, instance_id: str, parameters: dict[str, Any], **kwargs: Any
    ) -> tuple[Any, float, dict]:
        # 用后端 args_schema 校验 → 调后端真实 run();校验/执行错回文本给模型自纠,不抛崩 rollout。
        try:
            args = self._tool.args_schema(**parameters)
            result = await self._tool.run(args)
        except Exception as e:  # noqa: BLE001 — rollout 内任何工具异常都该转成可读反馈
            return ToolResponse(text=f"[tool error] {type(e).__name__}: {e}"), 0.0, {}
        text = (
            result
            if isinstance(result, str)
            else json.dumps(result, ensure_ascii=False, default=str)
        )
        return ToolResponse(text=text), 0.0, {}

    async def calc_reward(self, instance_id: str, **kwargs: Any) -> float:
        return 0.0  # 工具不给 reward;outcome reward 走 oracle_reward.compute_score

    async def release(self, instance_id: str, **kwargs: Any) -> None:
        self._instances.pop(instance_id, None)


__all__ = ["VerlBackendToolAdapter"]
