"""DD Plan Template — A4 design (v1.x).

Replaces v0.8.5 PLAN_REGISTRY 4-plan fork with a single template that declares
business constraints (required dims / tool palette / constraints) and lets the
LLM choose tools + args + optional dims within those constraints. Validator
(plan_validator.py) enforces the contract.

spec ref: docs/superpowers/specs/2026-05-15-v1.x-plan-template-validator-design.md § 4-5
"""

from __future__ import annotations

from typing import TypedDict

from app.agents.schemas import SubtaskTemplate, ToolName

__all__ = [
    "Constraints",
    "DD_PLAN_TEMPLATE",
    "DimensionSpec",
    "PlanTemplate",
    "SAFE_DEFAULT_PLAN",
]


class DimensionSpec(TypedDict):
    """A single research dimension declared in the plan template.

    name: human-readable dim name (e.g. "财务全景"). Validator checks
        subtask description/rationale contains this string.
    tool_candidates: tools the LLM may pick to cover this dim.
    min_tools: minimum unique tools (from candidates) required to satisfy
        coverage. 0 for optional dims.
    """
    name: str
    tool_candidates: list[ToolName]
    min_tools: int


class Constraints(TypedDict):
    """Template-level business constraints enforced by plan_validator.

    max_subtasks: hard cap on total subtask count per plan.
    max_tool_calls_per_subtask: max len(subtask.required_tools).
    forbid_duplicate_calls: when True, validator rejects a plan where a
        single subtask has the same tool twice in required_tools.
        Cross-subtask reuse is ALLOWED — same tool can appear in
        multiple subtasks (different analytical lens). DataCollector
        does call-level dedup separately via chat_known_tool_results.
    """
    max_subtasks: int
    max_tool_calls_per_subtask: int
    forbid_duplicate_calls: bool


class PlanTemplate(TypedDict):
    """Top-level plan template — declares dims + tool whitelist + constraints
    that bound LLM-generated ResearchPlan."""
    required_dimensions: list[DimensionSpec]
    optional_dimensions: list[DimensionSpec]
    tool_palette: list[ToolName]
    constraints: Constraints


DD_PLAN_TEMPLATE: PlanTemplate = {
    "required_dimensions": [
        {
            "name": "财务全景",
            "tool_candidates": ["get_financials", "get_balance_sheet", "get_cashflow"],
            "min_tools": 2,
        },
        {
            "name": "估值",
            "tool_candidates": ["get_pe_history", "get_daily_basic"],
            "min_tools": 1,
        },
        {
            "name": "行业地位",
            "tool_candidates": ["web_search", "kb_search"],
            "min_tools": 1,
        },
        {
            "name": "风险底线",
            "tool_candidates": ["get_holder_change", "get_news", "kb_search"],
            "min_tools": 1,
        },
    ],
    "optional_dimensions": [
        {"name": "近期催化", "tool_candidates": ["get_forecast", "get_news"], "min_tools": 0},
        {"name": "资金动向", "tool_candidates": ["get_money_flow"], "min_tools": 0},
        {"name": "同业对比", "tool_candidates": ["get_daily_basic"], "min_tools": 0},
    ],
    "tool_palette": [
        "get_financials", "get_balance_sheet", "get_cashflow",
        "get_pe_history", "get_daily_basic",
        "web_search", "kb_search",
        "get_holder_change", "get_news",
        "get_forecast", "get_money_flow",
    ],
    "constraints": {
        "max_subtasks": 10,
        "max_tool_calls_per_subtask": 3,
        "forbid_duplicate_calls": True,
    },
}


# Validator retry exhausted fallback — 7-subtask full-coverage plan.
SAFE_DEFAULT_PLAN: list[SubtaskTemplate] = [
    SubtaskTemplate(
        description_template="评估 {target_name}({ts_code}) 财务全景 — 三表完整 + ROE 趋势",
        rationale="财务全景是 DD 客观底稿基础",
        required_tools=("get_financials", "get_balance_sheet", "get_cashflow"),
    ),
    SubtaskTemplate(
        description_template="评估 {target_name}({ts_code}) 估值 — PE 历史分位",
        rationale="估值是配置决策的核心输入",
        required_tools=("get_pe_history", "get_daily_basic"),
    ),
    SubtaskTemplate(
        description_template="评估 {target_name}({ts_code}) 行业地位 — 行业研报 + KB 检索",
        rationale="行业地位决定长期竞争力",
        required_tools=("web_search", "kb_search"),
    ),
    SubtaskTemplate(
        description_template="评估 {target_name}({ts_code}) 风险底线 — 大股东动作 + 近期负面",
        rationale="风险底线避免重大事件",
        required_tools=("get_holder_change", "get_news"),
    ),
    SubtaskTemplate(
        description_template="评估 {target_name}({ts_code}) 近期催化 — 业绩预告 + 重大公告",
        rationale="近期催化驱动短期行情",
        required_tools=("get_forecast", "get_news"),
    ),
    SubtaskTemplate(
        description_template="评估 {target_name}({ts_code}) 资金动向 — 主力资金 + 龙虎榜",
        rationale="资金动向反映市场态度",
        required_tools=("get_money_flow",),
    ),
    SubtaskTemplate(
        description_template="评估 {target_name}({ts_code}) 同业对比 — 行业内估值对比",
        rationale="同业对比明确相对位置",
        required_tools=("get_daily_basic",),
    ),
]
