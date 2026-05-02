"""DataCollector — runs ResearchPlan.subtasks' required_tools in parallel.

Uses asyncio.gather for fan-out; failures of individual tools are caught
and recorded as ToolResult(success=False) so other tools still run.

Provides BOTH sync step() (unit-test entry) AND async collect_async()
(LangGraph node entry, avoids asyncio.run re-entry).
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.agents.base import Agent
from app.agents.schemas import ResearchState, StepResult, ToolCall, ToolResult
from app.services.llm_response import Tier
from app.services.llm_service import LLMService
from app.tools.registry import ToolRegistry


class DataCollector(Agent):
    name = "DataCollector"
    model_tier: Tier = "fast"  # nominal; doesn't actually call LLM directly

    def __init__(self, llm: LLMService, registry: ToolRegistry) -> None:
        super().__init__(llm)
        self._registry = registry

    def step(self, state: ResearchState) -> StepResult:  # type: ignore[override]
        """Sync entry — wraps asyncio.run for unit tests / non-async contexts.
        Use collect_async() inside LangGraph nodes (already in async loop)."""
        return asyncio.run(self.collect_async(state))

    async def collect_async(self, state: ResearchState) -> StepResult:
        if state.plan is None:
            return StepResult(
                state_update={"tool_results": []},
                span_metadata={"agent": "DataCollector"},
            )
        calls: list[ToolCall] = []
        for sub in state.plan.subtasks:
            for tool_name in sub.required_tools:
                args = _default_args_for(tool_name, state.plan.target_entity, state.user_message)
                calls.append(ToolCall(tool_name=tool_name, args=args, rationale=sub.rationale))
        results = await _execute_all(calls, self._registry)
        return StepResult(
            state_update={"tool_results": results},
            span_metadata={"agent": "DataCollector", "n_calls": len(calls)},
        )


async def _execute_all(calls: list[ToolCall], registry: ToolRegistry) -> list[ToolResult]:
    tasks = [registry.execute(c) for c in calls]
    return list(await asyncio.gather(*tasks))


def _default_args_for(tool_name: str, target: str, user_message: str) -> dict[str, Any]:
    """Heuristic default args based on tool name."""
    if tool_name == "get_stock_quote":
        return {"ts_code": target}
    if tool_name == "get_financials":
        return {"ts_code": target, "period": "latest"}
    if tool_name == "get_news":
        return {"ts_code": target if target else None, "n": 5, "days_back": 7}
    if tool_name == "web_search":
        return {"query": user_message, "search_type": "news", "count": 5}
    if tool_name == "kb_search":
        return {"query": user_message, "top_k": 5}
    return {}
