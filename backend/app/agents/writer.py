"""Writer — emits InvestmentDueDiligenceReport schema-conformant JSON (v0.8.4).

v0.8.3: adds alert_writer mode — when state.mode == "alert_deep_dive" the writer
produces a PortfolioWarningReport instead of an InvestmentDueDiligenceReport.

设计 ref: docs/superpowers/specs/2026-05-04-v0.8.4-b1-single-deep-design.md § 3
"""

from __future__ import annotations

from datetime import datetime

from app.agents.base import Agent
from app.agents.investment_dd_renderer import render_investment_dd_report_markdown
from app.agents.investment_dd_schema import InvestmentDueDiligenceReport
from app.agents.portfolio_warning_schema import PortfolioWarningReport
from app.agents.schemas import ResearchState, StepResult
from app.services.llm_response import Tier

_SYSTEM_PROMPT = """你是专业投资研究分析师。

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

**约束**:
- evidence 里的 chunk_id 必须来自下方 Insights 中出现的数据(不要凭空构造)
- narrative 用规范中文金融术语
- 风险等级客观评估:有重大风险信号时 overall_risk_level 选 high 或 very_high
- 无 Insight 支撑的内容在 narrative 里声明"数据缺失,建议补充材料"
"""


def build_credit_report_prompt(state: ResearchState) -> str:
    insights_str = "\n".join(
        f"- [{i.subtask_id}] {i.finding}(confidence={i.confidence})" for i in state.insights
    )
    return (
        _SYSTEM_PROMPT
        + f"\n\n# Insights\n{insights_str}\n"
        + f"\n# 用户原始需求 / 标的信息\n{state.user_message}\n"
        + f"\n# 本次 request_id(填入 JSON 的 request_id 字段)\n{state.request_id}\n"
        + "\n请严格按上方 JSON 模板输出,不要更改任何字段名。"
    )


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
        prompt = build_credit_report_prompt(state)
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
