"""ToolHub → task graph → policy/runtime → adapter integration coverage."""

from __future__ import annotations

import json
from typing import Any

import pytest
from app.chatloop.state import ChatLoopState
from app.chatloop.tool_hub import ToolHub
from app.chatloop.tool_runtime_policy import ToolRiskMetadata
from app.runtime.models import CapabilityType, RiskLevel
from app.services.llm_step import StepToolCall
from app.tools.base import Tool
from pydantic import BaseModel

pytestmark = pytest.mark.asyncio


class _SeedArgs(BaseModel):
    symbol: str


class _UseArgs(BaseModel):
    seed: dict[str, Any]


class _Tool(Tool):
    description = "integration tool"
    runtime_risk_metadata = ToolRiskMetadata(
        RiskLevel.LOW, CapabilityType.DATA_TOOL, True, True, max_attempts=2
    )

    def __init__(self, name: str, schema: type[BaseModel], output: dict[str, Any]) -> None:
        self.name = name
        self.args_schema = schema
        self._output = output
        self.calls = 0

    async def run(self, args: BaseModel) -> dict[str, Any]:
        del args
        self.calls += 1
        return self._output


class _Registry:
    def __init__(self, tools: list[Tool]) -> None:
        self._tools = {tool.name: tool for tool in tools}

    def list_for_llm(self) -> list[dict[str, Any]]:
        return [tool.schema_for_llm() for tool in self._tools.values()]

    def get(self, name: str) -> Tool:
        return self._tools[name]


def _call(call_id: str, name: str, args: dict[str, Any]) -> StepToolCall:
    return StepToolCall(id=call_id, name=name, arguments=json.dumps(args))


async def test_dependency_output_crosses_all_safety_layers_in_original_result_order() -> None:
    seed = _Tool("seed", _SeedArgs, {"access_token": "secret", "price": 10})
    use = _Tool("use", _UseArgs, {"done": True})
    hub = ToolHub()
    hub.register_registry(_Registry([seed, use]))
    state = ChatLoopState(
        user_id="user",
        session_id="turn",
        request_id="request",
        messages=[{"role": "user", "content": "compare"}],
        step=1,
    )

    results = await hub.dispatch(
        [
            _call("provider-1", "seed", {"__task_id": "seed-task", "symbol": "X"}),
            _call(
                "provider-2",
                "use",
                {
                    "__task_id": "use-task",
                    "seed": "$task.seed-task.output",
                },
            ),
        ],
        state,
    )

    assert [result.tool_name for result in results] == ["seed", "use"]
    assert results[0].output == {"access_token": "[REDACTED]", "price": 10}
    assert results[1].args == {"seed": {"access_token": "[REDACTED]", "price": 10}}
    assert seed.calls == use.calls == 1
