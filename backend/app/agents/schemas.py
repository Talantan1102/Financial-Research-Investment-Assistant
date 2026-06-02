"""Agent I/O Pydantic schemas — stable v0~v3.

ChatState (née GraphState) is the LangGraph state object (mutable across nodes).
Plan / ToolCall / ToolResult / StepResult are agent-level frozen contracts.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agents.debate_schemas import DebateTrace
from app.agents.escalation_protocol import Entity, Preference, ToolResultRef
from app.agents.investment_dd_schema import InvestmentDueDiligenceReport, ValuationAnalysis
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


# C71: PlanId removed — only referenced by deprecated plan_registry.py (deleted).
# InvestmentObjective (above) covers the same 4-value domain for live callers.


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
    cached: bool = False  # v0.9: True when result came from ToolResultCache (B3)
    tool_call_data: dict[str, Any] | None = None  # Plan 2b: skill_script metadata


class SkillScriptCall(BaseModel):
    """One execute_script action emitted by ChatPlanner."""

    skill: str
    script: str  # relative path, e.g. "scripts/calculate_dcf.py"
    args: dict[str, Any] = Field(default_factory=dict)


class Plan(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool_calls: list[ToolCall]
    direct_response: bool
    reasoning: str

    # === v0.9 NEW ===
    parallelizable: bool = False  # A2: parallel tool dispatch
    escalate_offered: bool = False  # Q3: Plan 3 escalation hook
    escalate_reason: str | None = None  # human-readable; SSE event payload

    # === Plan 2a NEW (S2: skill context loader) ===
    load_skill: str | None = Field(
        default=None,
        description="Skill name to expand from L1 to L2 (with L3a resources).",
    )
    load_resource: dict | None = Field(
        default=None,
        description="Specific resource to load: {'skill': str, 'ref': str}.",
    )

    # === Plan 2b NEW ===
    script_calls: list[SkillScriptCall] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_consistency(self) -> Plan:
        if self.direct_response and self.tool_calls:
            raise ValueError("direct_response=True 时 tool_calls 必须为空")
        has_action = (
            bool(self.tool_calls)
            or self.escalate_offered
            or self.load_skill is not None
            or self.load_resource is not None
            or bool(self.script_calls)
        )
        if not self.direct_response and not has_action:
            raise ValueError(
                "direct_response=False 时 tool_calls 至少有 1 个"
                "（或 escalate_offered=True / load_skill / load_resource / script_calls）"
            )
        return self


class StepResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    state_update: dict[str, Any]
    span_metadata: dict[str, Any] = Field(default_factory=dict)


class HistoryMessage(BaseModel):
    """One turn in chat history (v0.9 Q4-E memory)."""

    model_config = ConfigDict(frozen=True)

    role: Literal["user", "assistant", "tool"]
    content: str
    turn_index: int
    tool_call_id: str | None = None
    tool_name: str | None = None
    timestamp: datetime


class CacheEntry(BaseModel):
    """One cached tool result for cross-turn dedup (C1)."""

    model_config = ConfigDict(frozen=True)

    tool_name: str
    args_hash: str
    result_summary: str
    cache_id: str  # → ToolResultCache PK
    cached_at: datetime


class ChatState(BaseModel):
    """v0.9 chat agent graph state.

    Layout per spec § 4.1.  Fields in 6 groups:
      1. legacy v0 (user_id / session_id / user_message / request_id)
      2. Q4 E memory (history / history_summary)
      3. tool result mgmt (tool_results / tool_result_cache)
      4. plan + final (legacy plan; final_response)
      5. escalation hooks (Plan 3 will use these; Plan 1 reserves)
      6. observability (trace_request_id / span_stack / cost_so_far)
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    # === legacy v0 ===
    user_id: str
    session_id: str
    user_message: str
    request_id: str

    # === v0 placeholders (preserved for backwards-compat) ===
    enable_web_search: bool = False
    enable_kb_search: bool = False

    # === Q4 E memory ===
    history: list[HistoryMessage] = Field(default_factory=list)
    history_summary: str | None = None

    # === tool result mgmt (Plan 1 + B1/B2/B3/C1) ===
    tool_results: list[ToolResult] = Field(default_factory=list)
    tool_result_cache: dict[str, CacheEntry] = Field(default_factory=dict)

    # === legacy plan ===
    plan: Plan | None = None
    final_response: str | None = None
    final_response_streamed: bool = False

    # === escalation (Plan 3 deliverable; Plan 1 reserves only) ===
    escalate_offered: bool = False
    escalate_confirmed: bool = False

    # === Plan 2a skill loader hook ===
    skill_context: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Loaded skill bundles (L2 SKILL.md + concatenated L3a resources). "
            "Keyed by skill name. Persisted across planner turns via LangGraph checkpointer."
        ),
    )

    # === C.5 Plan 6 — Memory vs KB routing ===
    retrieval_targets: list[str] = Field(
        default_factory=list,
        description=(
            "Output of memory_kb_router_node — single-element list "
            "containing 'memory' / 'kb' / 'both'. Empty before router runs."
        ),
    )
    memory_hits: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "archival_memory_search results when retrieval_targets includes memory/both. "
            "Serialized ChatMemoryEdge dicts."
        ),
    )
    kb_hits: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "KbSearchService.search results when retrieval_targets includes kb/both. "
            "Serialized KbHit dicts."
        ),
    )
    memory_kb_routing_reasoning: str | None = Field(
        default=None,
        description="Reasoning string from memory_kb_router for trace/debug.",
    )

    # === observability ===
    trace_request_id: str
    span_stack: list[str] = Field(default_factory=list)
    cost_so_far: float = 0.0

    @model_validator(mode="after")
    def _check_retrieval_targets_field(self) -> ChatState:
        for t in self.retrieval_targets:
            if t not in ("memory", "kb", "both"):
                raise ValueError(f"Invalid retrieval target in ChatState: {t!r}")
        return self


# Backwards-compatibility alias for callers still importing GraphState.
# Remove in v1.0 once all callers migrate to ChatState.
GraphState = ChatState


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
    """ResearchPlanner 输出 — v1.x A4 template-guided schema.

    The planner LLM emits a full subtask list (description + rationale + tool
    selection) within DD_PLAN_TEMPLATE constraints. plan_validator.validate_plan
    enforces; retry ≤2 then fallback to SAFE_DEFAULT_PLAN.

    plan_id (v0.8.5 constrained-router 4-plan selector) removed — see
    docs/superpowers/specs/2026-05-15-v1.x-plan-template-validator-design.md § 4.
    """

    model_config = ConfigDict(extra="ignore")

    rationale: str = Field(max_length=300, description="LLM 解释 plan 生成逻辑")
    subtasks: list[Subtask] = Field(
        min_length=1,
        description="LLM 在 template 约束内生成的 subtask 列表",
    )


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
    "valuation_consistency",  # v1.x A5a (第 7 维)
    "dialectical_balance",  # v1.x A5b (第 8 维)
    # plan_correctness removed in v1.x (Validator replaces it; see 2026-05-15 spec § 7.1)
]


class CriticDimensionScore(BaseModel):
    """Critic 单维度评分。"""

    model_config = ConfigDict(frozen=True)

    dimension: CriticDimension
    score: float = Field(ge=0.0, le=10.0)
    evidence: str
    sub_agent_request_id: str
    # C18: optional-feature scorers (A5a valuation cross-check / A5b debate) return a
    # score=10.0 sentinel when their feature was not run. aggregate_scores excludes
    # is_skip dims so those 10.0s don't inflate overall_score.
    is_skip: bool = False


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
    # ge=0/le=2 mirrors _MAX_PLANNER_RETRY in research_graph.py — hard cap so the
    # retry router cannot loop indefinitely even if state is corrupted upstream.
    target_entity: str | None = None  # e.g. "贵州茅台"; falls back to ts_code if None
    planner_retry_count: int = Field(default=0, ge=0, le=2)
    planner_critic_feedback: str | None = Field(default=None, max_length=300)
    # v1.x — writer retry state (spec 2026-05-15 § 7.2; replaces planner retry).
    # Planner is now Validator-gated → "wrong plan" can't reach Critic;
    # the real failure mode is Writer using data sloppily → factuality < 7.0.
    writer_retry_count: int = Field(default=0, ge=0, le=1)
    writer_critic_feedback: str | None = Field(default=None, max_length=300)
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

    # === Plan 3 — chat-derived fields ===
    chat_extracted_entities: list[Entity] = Field(default_factory=list)
    chat_extracted_preferences: list[Preference] = Field(default_factory=list)
    chat_known_tool_results: list[ToolResultRef] = Field(default_factory=list)
    chat_session_id: str | None = None

    # v1.x — multi-turn distillation fields (spec § 6.4; mirrors EscalationPacket).
    # Injected via state_overrides when escalation router decides confidence ≥ threshold.
    # Empty defaults mean "form-style direct entry" path (no chat distillation available).
    escalation_intent: str = Field(default="", max_length=200)
    discussion_focus: list[str] = Field(default_factory=list, max_length=5)
    explicit_exclusions: list[str] = Field(default_factory=list, max_length=3)

    # v1.x A5a: DCF inputs (DataCollector populates in Task 15 wire)
    forecast_growth: float | None = Field(
        default=None,
        description=(
            "tushare get_forecast 业绩预告增速 (e.g. 0.10 = 10%);"
            "缺则 None,DCF helper 走 historical fallback"
        ),
    )
    price_history_for_beta: list[dict[str, Any]] | None = Field(
        default=None,
        description=(
            "近 60 日 OHLC + 沪深 300 close;Analyst 用以算 60-day β。"
            "结构: [{trade_date, close, index_close}, ...]"
        ),
    )

    # v1.x A5a: Analyst 算出来的 multi-model cross-check 结果。Writer
    # post_process_writer_output 在 LLM call 之后拷到
    # InvestmentDueDiligenceReport.financial_analysis.valuation_analysis,
    # 覆盖 LLM 占位 — 保证 Python 决定论是 single source of truth。
    valuation_analysis: ValuationAnalysis | None = Field(
        default=None,
        description=(
            "v1.x A5a Analyst 节点产出的多模型估值 cross-check;"
            "Writer post_process 拷到 report.financial_analysis.valuation_analysis"
        ),
    )

    # v1.x A5b: Bull/Bear debate 完整 trace
    debate_trace: DebateTrace | None = Field(
        default=None,
        description="v1.x A5b: 4 round LLM call 完整 trace + 总 cost + latency",
    )
