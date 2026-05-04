"""DataCollector — runs ResearchPlan.subtasks' required_tools in parallel.

Uses asyncio.gather for fan-out; failures of individual tools are caught
and recorded as ToolResult(success=False) so other tools still run.

Provides BOTH sync step() (unit-test entry) AND async collect_async()
(LangGraph node entry, avoids asyncio.run re-entry).

v0.8.4: _default_args_for uses state.target_ts_code (structured field) as primary
        routing key; falls back to heuristic extraction from user_message.
        web_search / kb_search queries are enriched with investment_objective /
        investment_horizon context from state when available.
"""

from __future__ import annotations

import asyncio
import re
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

        # Resolve target entity: prefer structured ts_code field, fall back to heuristic
        target = state.target_ts_code or _extract_target_from_message(state.user_message)

        calls: list[ToolCall] = []
        for sub in state.plan.subtasks:
            for tool_name in sub.required_tools:
                args = _default_args_for(
                    tool_name=tool_name,
                    target=target,
                    state=state,
                )
                calls.append(ToolCall(tool_name=tool_name, args=args, rationale=sub.rationale))
        results = await _execute_all(calls, self._registry)
        return StepResult(
            state_update={"tool_results": results},
            span_metadata={"agent": "DataCollector", "n_calls": len(calls)},
        )


async def _execute_all(calls: list[ToolCall], registry: ToolRegistry) -> list[ToolResult]:
    tasks = [registry.execute(c) for c in calls]
    return list(await asyncio.gather(*tasks))


def _extract_target_from_message(user_message: str) -> str:
    """Heuristic: 提取 .SH/.SZ 股票代码;否则返回空让 LLM 自己识别。"""
    m = re.search(r"\b\d{6}\.(SH|SZ)\b", user_message)
    return m.group(0) if m else ""


def _build_context_enriched_query(base_query: str, state: ResearchState) -> str:
    """Enrich search query with investment context for more targeted results."""
    objective = state.investment_objective
    horizon = state.investment_horizon

    suffix_parts: list[str] = []
    if objective == "capital_preservation":
        suffix_parts.append("风险评估 信用安全 偿债能力")
    elif objective == "stable_growth":
        suffix_parts.append("基本面 分红 股息 盈利质量")
    elif objective == "aggressive_growth":
        suffix_parts.append("成长性 业绩增速 行业催化")

    if horizon == "short_term":
        suffix_parts.append("近期动态")
    elif horizon == "long_term":
        suffix_parts.append("长期竞争优势 行业格局")

    if suffix_parts:
        return f"{base_query} {' '.join(suffix_parts)}"
    return base_query


def _default_args_for(tool_name: str, target: str, state: ResearchState) -> dict[str, Any]:
    """Heuristic default args based on tool name, using structured state fields."""
    if tool_name == "get_stock_quote":
        return {"ts_code": target}
    if tool_name == "get_financials":
        return {"ts_code": target, "period": "latest"}
    if tool_name == "get_news":
        return {"ts_code": target if target else None, "n": 5, "days_back": 7}
    if tool_name == "web_search":
        base_query = state.user_message
        return {
            "query": _build_context_enriched_query(base_query, state),
            "search_type": "news",
            "count": 5,
        }
    if tool_name == "kb_search":
        base_query = state.user_message
        return {
            "query": _build_context_enriched_query(base_query, state),
            "top_k": 5,
        }
    return {}
