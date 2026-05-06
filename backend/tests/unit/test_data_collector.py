"""L0 — DataCollector parallel tool execution + failure resilience."""

from typing import Any

import pytest
from app.agents.data_collector import DataCollector
from app.agents.schemas import ResearchPlan, ResearchState, Subtask
from app.services.llm_mock_client import MockLLMClient
from app.services.llm_service import LLMService
from app.tools.base import Tool, ToolError
from app.tools.registry import ToolRegistry
from pydantic import BaseModel


class _Args(BaseModel):
    x: int = 0


class _OkTool(Tool):
    name = "ok"
    description = "Returns x doubled"
    args_schema = _Args

    async def run(self, args: BaseModel) -> dict[str, Any]:
        if not isinstance(args, _Args):
            raise ToolError("type")
        return {"y": args.x * 2}


class _FailTool(Tool):
    name = "fail"
    description = "Always fails"
    args_schema = _Args

    async def run(self, args: BaseModel) -> dict[str, Any]:
        raise ToolError("intended")


@pytest.mark.asyncio
async def test_data_collector_parallel_success(
    mock_llm_client: MockLLMClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_MODE", "mock")
    reg = ToolRegistry()
    reg.register(_OkTool())

    plan = ResearchPlan(
        plan_id="balanced",
        rationale="default test plan",
        subtasks=[
            Subtask(subtask_id="s1", description="d1", required_tools=["ok"], rationale="r"),
            Subtask(subtask_id="s2", description="d2", required_tools=["ok"], rationale="r"),
        ],
    )
    state = ResearchState(
        user_id="u", session_id="s", user_message="m", request_id="r-1", plan=plan
    )

    collector = DataCollector(llm=LLMService(client=mock_llm_client), registry=reg)
    sr = await collector.collect_async(state)

    results = sr.state_update["tool_results"]
    successes = [r for r in results if r.success]
    n_succ = len(successes)
    assert n_succ >= 2  # 2 subtasks each call 1 tool


@pytest.mark.asyncio
async def test_data_collector_partial_failure_does_not_block(
    mock_llm_client: MockLLMClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_MODE", "mock")
    reg = ToolRegistry()
    reg.register(_OkTool())
    reg.register(_FailTool())

    plan = ResearchPlan(
        plan_id="balanced",
        rationale="default test plan",
        subtasks=[
            Subtask(
                subtask_id="s1",
                description="d1",
                required_tools=["ok", "fail"],
                rationale="r",
            ),
        ],
    )
    state = ResearchState(
        user_id="u", session_id="s", user_message="m", request_id="r-2", plan=plan
    )

    collector = DataCollector(llm=LLMService(client=mock_llm_client), registry=reg)
    sr = await collector.collect_async(state)

    results = sr.state_update["tool_results"]
    n_total = len(results)
    assert n_total == 2
    n_success = sum(1 for r in results if r.success)
    n_fail = sum(1 for r in results if not r.success)
    assert n_success == 1
    assert n_fail == 1
