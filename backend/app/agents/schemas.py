"""Agent I/O Pydantic schemas — stable v0~v3.

GraphState is the LangGraph state object (mutable across nodes).
Plan / ToolCall / ToolResult / StepResult are agent-level frozen contracts.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agents.credit_report_schema import CreditInvestigationReport
from app.agents.portfolio_warning_schema import PortfolioWarningReport
from app.services.monitoring.signal_rules.base import SignalResult


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
    required_tools: list[str]
    rationale: str


class ResearchPlan(BaseModel):
    """ResearchPlanner 输出。"""

    model_config = ConfigDict(frozen=True)

    subtasks: list[Subtask]
    target_entity: str
    research_style: Literal["concise", "comprehensive"]
    reasoning: str


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


CriticDimension = Literal["factuality", "coverage", "insight", "structure", "conciseness"]


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


class ResearchState(BaseModel):
    """LangGraph 研报状态(类比 v0 GraphState)。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    user_id: str
    session_id: str
    user_message: str
    request_id: str

    plan: ResearchPlan | None = None
    tool_results: list[ToolResult] = Field(default_factory=list)
    insights: list[Insight] = Field(default_factory=list)
    report_markdown: str | None = None
    chart_specs: list[ChartSpec] = Field(default_factory=list)
    credit_report: CreditInvestigationReport | None = None
    critic_report: CriticReport | None = None

    span_stack: list[str] = Field(default_factory=list)

    # v0.8.3 — alert mode for portfolio monitoring (B-3)
    mode: Literal["full_research", "alert_deep_dive"] = "full_research"
    alert_signals: list[SignalResult] | None = None
    portfolio_warning_report: PortfolioWarningReport | None = None
    deep_dive_section: str | None = None
