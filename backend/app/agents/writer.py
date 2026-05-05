"""Writer — emits InvestmentDueDiligenceReport schema-conformant JSON (v0.8.4).

v0.8.3: adds alert_writer mode — when state.mode == "alert_deep_dive" the writer
produces a PortfolioWarningReport instead of an InvestmentDueDiligenceReport.

v0.8.4: build_investment_dd_prompt is conditioned on all 6 input fields:
  - investment_objective → § 5 risk framing + § 6 recommendation tone
  - investment_horizon   → § 6 recommended_holding_period guidance
  - risk_tolerance       → § 6 position-size hint + entry/stop constraints
  - client_total_aum     → § 6 position size CNY anchor
  - client_existing_position → § 6 加/持/减 decision framing
  - target_ts_code       → data anchor throughout

v0.8.5: prompt appended with composed_sop() (11 methodology dimensions). § 6
recommendation enum + recommended_position_size_pct are now overridden by a
deterministic Python helper post_process_writer_output() — the LLM no longer
gets the final say on those two fields. Skill bundle scripts
(compute_position_size_pct + classify_recommendation) are the single source of
truth.

spec ref: docs/superpowers/specs/2026-05-04-v0.8.4-b1-single-deep-design.md § 3 / § 5.3
spec ref: docs/superpowers/specs/2026-05-04-v0.8.5-constrained-router-design.md § Task 5
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.agents.base import Agent
from app.agents.investment_dd_renderer import render_investment_dd_report_markdown
from app.agents.investment_dd_schema import InvestmentDueDiligenceReport
from app.agents.portfolio_warning_schema import PortfolioWarningReport
from app.agents.schemas import Recommendation, ResearchState, StepResult
from app.services.llm_response import Tier
from app.skills.financial_research import load_skill
from app.skills.financial_research.scripts import (
    classify_recommendation,
    compute_position_size_pct,
)

# Module-level skill load — methodology + references parsed once at import time.
_SKILL_BUNDLE = load_skill()
_SOP_TEXT = _SKILL_BUNDLE.composed_sop()


# ---------------------------------------------------------------------------
# Investment-objective–specific § 6 framing blocks
# ---------------------------------------------------------------------------

_OBJECTIVE_SECTION6_GUIDANCE: dict[str, str] = {
    "capital_preservation": (
        "投资目标为 capital_preservation(保本保值):§ 6 建议必须保守——"
        "recommendation 优先选 recommend_hold / recommend_underweight / recommend_sell;"
        "recommended_position_size_pct 不超过风险容忍度上限的 60%;"
        "recommended_stop_loss_price 必须比建议入场价低不超过 5%;"
        "position_management_conditions 至少含 1 条止损触发条件。"
        "§ 6 narrative 必须明确提及 capital_preservation 目标(如'基于您保本保值的投资目标' / "
        "'capital_preservation 客户应优先保障本金安全'等)以及客户的保守型风险承受度。"
    ),
    "stable_growth": (
        "投资目标为 stable_growth(稳健增长):§ 6 建议取中性偏多——"
        "recommendation 可选 recommend_buy / recommend_overweight / recommend_hold;"
        "recommended_position_size_pct 按中等风险容忍度计算;"
        "stop_loss 距入场价 8-12%;"
        "position_management_conditions 至少含 1 条分批建仓 + 1 条止损条件。"
        "§ 6 narrative 必须明确提及 stable_growth 目标(如'基于您稳健增长的投资目标'等)。"
    ),
    "balanced": (
        "投资目标为 balanced(均衡配置):§ 6 建议平衡收益与风险——"
        "recommendation 可选全档位(根据研究结论决定);"
        "recommended_position_size_pct 按 risk_tolerance 正常计算;"
        "stop_loss 距入场价 8-15%;"
        "position_management_conditions 覆盖加仓 / 减仓 / 止损三类。"
        "§ 6 narrative 必须明确提及 balanced 均衡配置目标(如'基于您 balanced 均衡型的投资目标' / "
        "'均衡配置策略下建议兼顾成长与防御'等)以及客户的 moderate 风险承受度。"
    ),
    "aggressive_growth": (
        "投资目标为 aggressive_growth(激进成长):§ 6 建议可偏进取——"
        "recommendation 可选 recommend_buy / recommend_overweight(若研究结论支持);"
        "recommended_position_size_pct 按 risk_tolerance 上限计算;"
        "stop_loss 可设在入场价 12-20% 以下(成长型允许更大波动容忍);"
        "position_management_conditions 至少含 1 条上涨目标价分批减仓条件。"
        "§ 6 narrative 必须明确提及 aggressive_growth 目标(如'基于您激进成长的投资目标' / "
        "'aggressive_growth 客户可追求高成长弹性'等)以及客户的高风险容忍度。"
    ),
}

_HORIZON_HOLDING_PERIOD_HINT: dict[str, str] = {
    "short_term": "recommended_holding_period 选 short_term",
    "medium_term": "recommended_holding_period 选 medium_term",
    "long_term": "recommended_holding_period 选 long_term",
}


def _build_section6_constraint_block(state: ResearchState) -> str:
    """Build § 6 constraint block conditioned on all 6 input fields.

    v0.8.5 — uses skill bundle compute_position_size_pct to derive the prompt-
    side hint number. Final value is overridden in post_process_writer_output(),
    so this is purely a narrative anchor.
    """
    objective = state.investment_objective or "balanced"
    risk_tolerance = state.risk_tolerance or "moderate"
    investment_horizon = state.investment_horizon or "medium_term"
    client_total_aum = state.client_total_aum or 0.0
    existing_position = state.client_existing_position

    # Compute suggested position size pct (prompt narrative anchor only — final
    # value is set deterministically in post_process_writer_output).
    suggested_pct_buy = compute_position_size_pct(
        recommendation="recommend_buy",
        risk_tolerance=risk_tolerance,
        market_cap_cny=1_000_000_000_000.0,  # default large-cap anchor
    )

    objective_block = _OBJECTIVE_SECTION6_GUIDANCE.get(
        objective, _OBJECTIVE_SECTION6_GUIDANCE["balanced"]
    )
    horizon_hint = _HORIZON_HOLDING_PERIOD_HINT.get(
        investment_horizon, _HORIZON_HOLDING_PERIOD_HINT["medium_term"]
    )

    existing_str = (
        f"- client_existing_position(现有持仓): {existing_position:,.0f} CNY"
        if existing_position is not None
        else "- client_existing_position: 无现有持仓(新建仓)"
    )

    return f"""
## § 6 投资建议约束(必须严格遵守)

**客户背景**:
- investment_objective: {objective}
- investment_horizon: {investment_horizon}  → {horizon_hint}
- risk_tolerance: {risk_tolerance}
- client_total_aum(客户总资产管理规模): {client_total_aum:,.0f} CNY
{existing_str}

**仓位计算规则**:
- recommended_position_size_pct 是占 client_total_aum 的百分比
- buy 建议下,{risk_tolerance} 风险容忍度对应建议仓位上限约 {suggested_pct_buy:.1f}%
- 对应绝对金额约 {client_total_aum * suggested_pct_buy / 100:,.0f} CNY
- 非 buy 建议(hold / sell)应相应调低仓位

**目标特定指令**:
{objective_block}

**价格区间约束**:
- recommended_entry_price_range 和 recommended_stop_loss_price 必须基于 Insights 中的实际价格数据
- estimated_target_price_range 必须与研究结论一致(不能凭空填高目标价)
- 所有价格字段不能为 0.0(若数据缺失请声明"建议补充行情数据")
"""


_SYSTEM_PROMPT_BASE = """你是专业投资研究分析师。

任务:基于已收集的 Insights + 用户提供的标的信息,产出一份**投资标的尽调报告**。

**输出格式(绝对严格)**:
- 直接输出一个 JSON 对象,**不要**套任何外层 key
- 字段名必须严格按照下方模板,**不得**自行更名
- **禁止**输出 markdown、解释文字、code fence

**JSON 模板**(字段名和结构不可变):
{
  "target_name": "<标的全称>",
  "target_ts_code": "<股票代码,如 600519.SH>",
  "request_id": "<沿用输入的 request_id>",
  "generated_at": "<ISO8601 时间,如 2026-05-04T10:00:00>",
  "target_close_price_at_gen": null,
  "target_market_cap_at_gen": null,
  "target_overview": {
    "narrative": "<100-300 字综述>",
    "registered_capital": "<注册资本或 null>",
    "main_business": "<主营业务一句话>",
    "controlling_shareholder": "<实际控制人或 null>",
    "listing_status": "<上市/非上市 + 板块或 null>",
    "current_pe": null,
    "current_pb": null,
    "current_market_cap": null,
    "dividend_yield": null,
    "evidence": ["<chunk_id_1>", "..."]
  },
  "legal_qualification": {
    "narrative": "<200-400 字综述>",
    "legal_status": "<法律主体合规情况>",
    "business_qualifications": ["<资质1>"],
    "adverse_records": [],
    "evidence": ["<chunk_id>"]
  },
  "financial_analysis": {
    "narrative": "<400-800 字深度分析>",
    "key_metrics": [
      {"name": "<指标名>", "value": "<指标值>", "period": "<期间>", "yoy_change": "<同比变化或 null>"}
    ],
    "profitability_analysis": "<盈利质量分析>",
    "growth_analysis": "<成长性分析>",
    "return_analysis": "<投资回报分析>",
    "cash_flow_analysis": "<现金流分析>",
    "valuation_analysis": {
      "narrative": "<估值分析综述>",
      "pe_historical_percentile": "<PE 历史百分位或 null>",
      "dcf_valuation": "<DCF 估值或 null>",
      "peer_comparison": "<同业估值对比或 null>"
    },
    "year_over_year_summary": "<同比变化或 null>",
    "evidence": ["<chunk_id>"]
  },
  "industry_analysis": {
    "narrative": "<300-600 字>",
    "industry_name": "<所属行业>",
    "industry_outlook": "<景气度判断>",
    "competitive_position": "<竞争地位>",
    "key_competitors": ["<对手1>"],
    "policy_impact": "<政策影响>",
    "evidence": ["<chunk_id>"]
  },
  "risk_assessment": {
    "narrative": "<300-500 字>",
    "market_risk": [
      {"title": "<风险标题>", "description": "<描述>", "severity": "low|medium|high", "mitigations": ["<措施>"]}
    ],
    "growth_risk": [
      {"title": "<>", "description": "<>", "severity": "low|medium|high", "mitigations": []}
    ],
    "event_risk": [
      {"title": "<>", "description": "<>", "severity": "low|medium|high", "mitigations": []}
    ],
    "valuation_risk": [
      {"title": "<>", "description": "<>", "severity": "low|medium|high", "mitigations": []}
    ],
    "overall_risk_level": "low|medium|high|very_high",
    "evidence": ["<chunk_id>"]
  },
  "investment_recommendation": {
    "narrative": "<200-400 字综合建议>",
    "recommendation": "recommend_buy|recommend_overweight|recommend_hold|recommend_underweight|recommend_sell",
    "recommended_position_size_pct": 5.0,
    "recommended_holding_period": "short_term|medium_term|long_term",
    "recommended_entry_price_range": {"low": 0.0, "high": 0.0},
    "recommended_stop_loss_price": 0.0,
    "estimated_target_price_range": {"low": 0.0, "high": 0.0},
    "position_management_conditions": ["<条件>"],
    "evidence": ["<chunk_id>"]
  }
}

**通用约束**:
- evidence 里的 chunk_id 必须来自下方 Insights 中出现的数据(不要凭空构造)
- narrative 用规范中文金融术语
- 风险等级客观评估:有重大风险信号时 overall_risk_level 选 high 或 very_high
- 无 Insight 支撑的内容在 narrative 里声明"数据缺失,建议补充材料"
"""


def build_investment_dd_prompt(state: ResearchState) -> str:
    """Build writer prompt conditioned on all 6 input fields.

    § 6 position size constraints, holding period hint, and objective-specific
    recommendation framing are all derived from structured input fields.
    """
    # Client context block (referenced at top of system prompt)
    objective = state.investment_objective or "balanced"
    horizon = state.investment_horizon or "medium_term"
    risk_tol = state.risk_tolerance or "moderate"
    aum = state.client_total_aum or 0.0

    client_context = (
        f"\n## 客户背景(必须在报告各章节中体现)\n"
        f"- investment_objective: {objective}\n"
        f"- investment_horizon: {horizon}\n"
        f"- risk_tolerance: {risk_tol}\n"
        f"- client_total_aum: {aum:,.0f} CNY\n"
    )
    if state.client_existing_position is not None:
        client_context += f"- client_existing_position: {state.client_existing_position:,.0f} CNY\n"

    # § 5 risk_assessment framing based on objective
    risk_framing = (
        "\n**§ 5 风险评估要求**:\n"
        f"客户投资目标为 {objective},请确保 risk_assessment 的 narrative 和 overall_risk_level "
        "反映该客户对风险的关注程度——"
    )
    if objective == "capital_preservation":
        risk_framing += (
            "保本客户对任何重大风险高度敏感,如存在 medium 以上风险应明确指出并给出缓解措施。"
        )
    elif objective == "aggressive_growth":
        risk_framing += "成长型客户可接受较高波动,但仍需客观评估系统性风险和行业颠覆风险。"
    else:
        risk_framing += "均衡客观地评估各类风险,不夸大也不淡化。"

    # § 6 constraint block (computed from all 6 fields)
    section6_block = _build_section6_constraint_block(state)

    # Insights summary
    insights_str = "\n".join(
        f"- [{i.subtask_id}] {i.finding}(confidence={i.confidence})" for i in state.insights
    )

    return (
        _SYSTEM_PROMPT_BASE
        + client_context
        + risk_framing
        + section6_block
        + f"\n\n# Insights\n{insights_str}\n"
        + f"\n# 用户原始需求 / 标的信息\n{state.user_message}\n"
        + f"\n# 本次 request_id(填入 JSON 的 request_id 字段)\n{state.request_id}\n"
        + f"\n# 投资研究员 SOP (跨 11 维度方法论)\n\n{_SOP_TEXT}\n"
        + "\n请严格按上方 JSON 模板输出,不要更改任何字段名。"
    )


# ---------------------------------------------------------------------------
# v0.8.5 post-processing — deterministic override of LLM-generated
# recommendation + position size. Skill bundle scripts are the single source
# of truth for these two fields.
# ---------------------------------------------------------------------------


def _extract_metrics_from_llm_report(report: dict[str, Any]) -> dict[str, Any]:
    """Extract metrics dict consumed by classify_recommendation.

    LLM-generated reports carry narrative text plus a few sparse numeric fields.
    We defensively pull what we can (`.get(...) or default`); fields the schema
    does not guarantee (`roe`, `revenue_yoy`, etc.) usually fall through to
    defaults, which causes classify_recommendation to drop to its `recommend_hold`
    fallback rule. That is the intended v0.8.5 baseline behaviour — refining
    metric extraction (parsing pe_historical_percentile str → float, etc.) is
    a future task. The deterministic override is what matters: LLM cannot
    talk the recommendation up.
    """
    fa: dict[str, Any] = report.get("financial_analysis") or {}
    va: dict[str, Any] = fa.get("valuation_analysis") or {}
    overview: dict[str, Any] = report.get("target_overview") or {}
    return {
        # NOTE: pe_historical_percentile in the schema is `str | None`
        # (e.g. "近 5 年 30 分位"). classify_recommendation's _eval_condition
        # silently catches type mismatch — string compared with float returns
        # False, no crash.
        "pe_percentile": va.get("pe_historical_percentile") or 0.5,
        "roe": fa.get("roe") or 0.0,
        "revenue_yoy": fa.get("revenue_yoy") or 0.0,
        "net_profit_yoy": fa.get("net_profit_yoy") or 0.0,
        "market_cap_cny": overview.get("current_market_cap") or 0.0,
        "forecast_signal": fa.get("forecast_signal") or "neutral",
        "asset_liability_warning": fa.get("debt_ratio_assessment") in {"警戒", "高风险"},
    }


def post_process_writer_output(
    state: ResearchState, llm_report: InvestmentDueDiligenceReport
) -> InvestmentDueDiligenceReport:
    """Override LLM-generated recommendation + position_size with deterministic Python.

    v0.8.5 single source of truth for § 6:
      - investment_recommendation.recommendation → classify_recommendation(metrics)
      - investment_recommendation.recommended_position_size_pct →
            compute_position_size_pct(rec, risk_tol, market_cap)

    All other fields (narrative, prices, holding_period, evidence) remain LLM-
    authored. Pure function — idempotent on a fixed (state, llm_report) pair.
    """
    report_dict = llm_report.model_dump()
    metrics = _extract_metrics_from_llm_report(report_dict)
    classified_rec: Recommendation = classify_recommendation(metrics)
    market_cap = float(metrics.get("market_cap_cny") or 0.0)
    risk_tolerance = state.risk_tolerance or "moderate"
    pct = compute_position_size_pct(
        recommendation=classified_rec,
        risk_tolerance=risk_tolerance,
        market_cap_cny=market_cap,
    )

    new_recommendation = llm_report.investment_recommendation.model_copy(
        update={
            "recommendation": classified_rec,
            "recommended_position_size_pct": pct,
        }
    )
    return llm_report.model_copy(update={"investment_recommendation": new_recommendation})


def _build_alert_prompt(state: ResearchState) -> str:
    signals = state.alert_signals or []
    signals_text = "\n".join(f"- {s.rule_name}({s.level.value}): {s.explanation}" for s in signals)
    return f"""为已触发以下信号的客户生成 PortfolioWarningReport JSON:

触发信号:
{signals_text}

要求:summary 100-200 字;triggered_signals 复制输入信号;risk_diagnosis.narrative 200-400 字;recommendations 至少 2 条.
"""


class Writer(Agent):
    name = "Writer"
    model_tier: Tier = "balanced"

    def step(self, state: ResearchState) -> StepResult:  # type: ignore[override]
        """Sync entry point — full_research mode only.

        For alert_deep_dive mode use the async run() method.
        """
        prompt = build_investment_dd_prompt(state)
        r = self._llm.chat(
            prompt=prompt,
            tier=self.model_tier,
            schema=InvestmentDueDiligenceReport,
            request_id=state.request_id,
        )
        if not isinstance(r.parsed, InvestmentDueDiligenceReport):
            raise RuntimeError(
                f"Writer expected InvestmentDueDiligenceReport from LLMService.chat(parsed=), "
                f"got {type(r.parsed).__name__}"
            )
        report = r.parsed
        # writer 覆盖 request_id 和 generated_at(LLM 输出値不可信)
        report = report.model_copy(
            update={
                "request_id": state.request_id,
                "generated_at": datetime.now(),
            }
        )
        # v0.8.5 — post-process: deterministic Python overrides for § 6
        # recommendation + recommended_position_size_pct.
        report = post_process_writer_output(state, report)

        markdown = render_investment_dd_report_markdown(report)

        return StepResult(
            state_update={
                "investment_report": report,
                "report_markdown": markdown,  # 兼容 SSE / 前端
                "chart_specs": [],  # v0.8.4 不做 chart;v0.8.5 加回
            },
            span_metadata={"agent": "Writer", "model": r.model, "cost_cny": r.cost_cny},
        )

    async def run(self, state: ResearchState) -> ResearchState:
        """Async entry point — dispatches on state.mode.

        - "full_research": delegates to sync step() and wraps in ResearchState
        - "alert_deep_dive": calls _run_alert_writer() to produce PortfolioWarningReport
        """
        if state.mode == "alert_deep_dive":
            return await self._run_alert_writer(state)
        return await self._run_full_research_writer(state)

    async def _run_full_research_writer(self, state: ResearchState) -> ResearchState:
        """Async wrapper around the sync step() for full_research mode."""
        sr = self.step(state)
        return state.model_copy(update=sr.state_update)

    async def _run_alert_writer(self, state: ResearchState) -> ResearchState:
        """Output PortfolioWarningReport (alert_deep_dive mode)."""
        prompt = _build_alert_prompt(state)
        response = self._llm.chat(
            prompt=prompt,
            tier="fast",  # alert deep_dive 短任务,走 fast
            schema=PortfolioWarningReport,
            request_id=state.request_id,
        )
        if response.parsed is None:
            # Defensive fallback — Writer 走 schema 模式未解析时直接抛
            raise RuntimeError("alert writer LLM returned no parsed PortfolioWarningReport")
        return state.model_copy(update={"portfolio_warning_report": response.parsed})
