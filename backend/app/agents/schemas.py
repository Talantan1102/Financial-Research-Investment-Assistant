"""Agent I/O Pydantic schemas — stable v0~v3.

GraphState is the LangGraph state object (mutable across nodes).
Plan / ToolCall / ToolResult / StepResult are agent-level frozen contracts.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agents.investment_dd_schema import InvestmentDueDiligenceReport
from app.agents.portfolio_warning_schema import PortfolioWarningReport
from app.services.monitoring.signal_rules.base import SignalResult

# ---------------------------------------------------------------------------
# v0.8.4 structured input enums
# ---------------------------------------------------------------------------

InvestmentObjective = Literal[
    "capital_preservation",
    "stable_growth",
    "balanced",
    "aggressive_growth",
]

InvestmentHorizon = Literal[
    "short_term",
    "medium_term",
    "long_term",
]

RiskTolerance = Literal[
    "conservative",
    "moderate",
    "balanced",
    "aggressive",
    "very_aggressive",
]

Recommendation = Literal[
    "recommend_buy",
    "recommend_overweight",
    "recommend_hold",
    "recommend_underweight",
    "recommend_sell",
]

# v0.8.5 — full tool catalog (5 existing + 8 new). Used by PLAN_REGISTRY's
# required_tools field type constraint so the planner can only choose from
# registered tool names.
ToolName = Literal[
    "get_stock_quote",
    "get_financials",
    "get_news",
    "web_search",
    "kb_search",
    "get_balance_sheet",
    "get_cashflow",
    "get_daily_basic",
    "get_pe_history",
    "get_forecast",
    "get_dividend_history",
    "get_holder_change",
    "get_money_flow",
]


# v0.8.5 — constrained-router plan_id catalog. Independent Literal from
# InvestmentObjective (semantic separation): InvestmentObjective is the
# user-facing investment goal; PlanId is the internal plan-template selector
# the planner LLM picks from PLAN_REGISTRY.
PlanId = Literal[
    "capital_preservation",
    "stable_growth",
    "balanced",
    "aggressive_growth",
]


class SubtaskTemplate(BaseModel):
    """Template for plan_registry — instantiated to Subtask at runtime.

    description_template uses {target_name} and {ts_code} placeholders that
    instantiate_plan() formats with concrete values per request.
    """

    model_config = ConfigDict(frozen=True)

    description_template: str
    rationale: str
    required_tools: tuple[ToolName, ...]


class ResearchRequest(BaseModel):
    """B-1 研报请求(v0.8.4 — 6 结构化字段 + 可选自由文本)。"""

    model_config = ConfigDict(extra="forbid")

    target_ts_code: str = Field(description="股票代码,如 600519.SH")
    client_total_aum: float = Field(description="客户总资产管理规模(CNY)")
    client_existing_position: float | None = Field(default=None, description="现有持仓(CNY,可选)")
    investment_objective: InvestmentObjective = Field(description="投资目标")
    investment_horizon: InvestmentHorizon = Field(description="投资期限")
    risk_tolerance: RiskTolerance = Field(description="风险承受度")
    user_message: str | None = Field(default=None, description="可选自由文本补充说明")


class ToolCall(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool_name: str
    args: dict[str, Any]
    rationale: str


class ToolResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool_name: str
    args: dict[str, Any]
    success: bool
    output: dict[str, Any] | None = None
    error: str | None = None
    latency_ms: int = Field(ge=0)


class Plan(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool_calls: list[ToolCall]
    direct_response: bool
    reasoning: str

    @model_validator(mode="after")
    def _check_consistency(self) -> Plan:
        if self.direct_response and self.tool_calls:
            raise ValueError("direct_response=True 时 tool_calls 必须为空")
        if not self.direct_response and not self.tool_calls:
            raise ValueError("direct_response=False 时 tool_calls 至少有 1 个")
        return self


class StepResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    state_update: dict[str, Any]
    span_metadata: dict[str, Any] = Field(default_factory=dict)


class GraphState(BaseModel):
    """LangGraph state — mutable across nodes."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    user_id: str
    session_id: str
    user_message: str
    enable_web_search: bool = False  # v0 placeholder
    enable_kb_search: bool = False  # v0 placeholder

    plan: Plan | None = None
    tool_results: list[ToolResult] = Field(default_factory=list)

    final_response: str | None = None
    final_response_streamed: bool = False

    request_id: str
    span_stack: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# v0.5 research-mode schemas — DO NOT modify v0 schemas above
# ---------------------------------------------------------------------------


class Subtask(BaseModel):
    """ResearchPlanner 输出的子任务。"""

    model_config = ConfigDict(frozen=True)

    subtask_id: str
    description: str
    # v0.8.4 兼容: kept as list[str] for legacy callers; planner-emitted instances
    # 实际全是 ToolName Literal (via instantiate_plan from typed SubtaskTemplate).
    required_tools: list[str]
    rationale: str


class ResearchPlan(BaseModel):
    """ResearchPlanner 输出 — v0.8.5 constrained-router schema.

    The planner LLM emits ``(plan_id, rationale)``; ``subtasks`` is then
    filled at runtime by ``instantiate_plan(plan_id, target_name, ts_code)``
    from PLAN_REGISTRY. Legacy v0.8.4 fields ``target_entity`` /
    ``research_style`` / ``reasoning`` kept as optional defaults so existing
    callers / tests that still construct ResearchPlan with them work
    unchanged (the planner itself no longer emits them).
    """

    # extra="ignore" so a hallucinated LLM emitting extra keys does not break
    # parsing. Not frozen — instantiate_plan's caller may need to overwrite
    # subtasks; downstream agents treat the instance as read-only by convention.
    model_config = ConfigDict(extra="ignore")

    plan_id: PlanId
    rationale: str = Field(max_length=200, description="LLM 解释为什么选此 plan_id")
    # subtasks 默认空, 由 instantiate_plan() runtime 填充 (Task 7 spec).
    subtasks: list[Subtask] = Field(default_factory=list)

    # v0.8.4 legacy compat (kept with defaults so existing tests/callers work).
    target_entity: str = ""
    research_style: Literal["concise", "comprehensive"] = "comprehensive"
    reasoning: str = ""


class Insight(BaseModel):
    """Analyst 输出的单个分析洞察。"""

    model_config = ConfigDict(frozen=True)

    subtask_id: str
    finding: str
    supporting_data: list[dict[str, Any]]
    confidence: Literal["high", "medium", "low"]


class ChartSpec(BaseModel):
    """Writer 产出的图占位元信息(v0.5 不渲染,留 v0.6 frontend)。"""

    model_config = ConfigDict(frozen=True)

    chart_id: str
    chart_type: Literal["line", "bar", "pie", "table"]
    title: str
    data: list[dict[str, Any]]
    x_axis: str | None = None
    y_axis: str | None = None


CriticDimension = Literal[
    "factuality",
    "coverage",
    "insight",
    "structure",
    "conciseness",
    "input_context_appropriateness",
]


class CriticDimensionScore(BaseModel):
    """Critic 单维度评分。"""

    model_config = ConfigDict(frozen=True)

    dimension: CriticDimension
    score: float = Field(ge=0.0, le=10.0)
    evidence: str
    sub_agent_request_id: str


class CriticReport(BaseModel):
    """Critic 聚合输出。"""

    model_config = ConfigDict(frozen=True)

    dimensions: list[CriticDimensionScore]
    overall_score: float = Field(ge=0.0, le=10.0)
    summary_markdown: str

    def get_score(self, dimension: CriticDimension) -> float | None:
        """Look up a single dimension score by name. Returns None if not found."""
        for d in self.dimensions:
            if d.dimension == dimension:
                return d.score
        return None


class ResearchState(BaseModel):
    """LangGraph 研报状态(类比 v0 GraphState)。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    user_id: str
    session_id: str
    user_message: str
    request_id: str

    # v0.8.4 — 6 structured input fields (synced from ResearchRequest)
    target_ts_code: str | None = None
    client_total_aum: float | None = None
    client_existing_position: float | None = None
    investment_objective: InvestmentObjective | None = None
    investment_horizon: InvestmentHorizon | None = None
    risk_tolerance: RiskTolerance | None = None

    plan: ResearchPlan | None = None
    tool_results: list[ToolResult] = Field(default_factory=list)

    # v0.8.5 — constrained router retry edge fields (Task 7 schema; Task 9 wires
    # the actual conditional retry edge in research_graph.py).
    target_entity: str | None = None  # e.g. "贵州茅台"; falls back to ts_code if None
    planner_retry_count: int = 0
    planner_critic_feedback: str | None = None
    insights: list[Insight] = Field(default_factory=list)
    report_markdown: str | None = None
    chart_specs: list[ChartSpec] = Field(default_factory=list)
    investment_report: InvestmentDueDiligenceReport | None = None
    critic_report: CriticReport | None = None

    span_stack: list[str] = Field(default_factory=list)

    # v0.8.3 — alert mode for portfolio monitoring (B-3)
    mode: Literal["full_research", "alert_deep_dive"] = "full_research"
    alert_signals: list[SignalResult] | None = None
    portfolio_warning_report: PortfolioWarningReport | None = None
    deep_dive_section: str | None = None
