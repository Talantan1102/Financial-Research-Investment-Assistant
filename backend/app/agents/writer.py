"""Writer — emits CreditInvestigationReport schema-conformant JSON (v0.8.2).

v0.8.3: adds alert_writer mode — when state.mode == "alert_deep_dive" the writer
produces a PortfolioWarningReport instead of a CreditInvestigationReport.

设计 ref: docs/superpowers/specs/2026-05-03-v0.8.2-credit-research-report-design.md § 3
"""

from __future__ import annotations

from datetime import datetime

from app.agents.base import Agent
from app.agents.credit_report_renderer import render_credit_report_markdown
from app.agents.credit_report_schema import CreditInvestigationReport
from app.agents.portfolio_warning_schema import PortfolioWarningReport
from app.agents.schemas import ResearchState, StepResult
from app.services.llm_response import Tier

_SYSTEM_PROMPT = """你是银行公司金融部 / 信贷研究分析师。

任务:基于已收集的 Insights + 用户提供的企业名 + 信贷场景,产出一份**信贷调查报告**。

**输出格式(绝对严格)**:
- 直接输出一个 JSON 对象,**不要**套任何外层 key
- 字段名必须严格按照下方模板,**不得**自行更名
- **禁止**输出 markdown、解释文字、code fence

**JSON 模板**(字段名和结构不可变):
{
  "company_name": "<企业全称>",
  "request_id": "<沿用输入的 request_id>",
  "generated_at": "<ISO8601 时间,如 2026-05-03T10:00:00>",
  "company_overview": {
    "narrative": "<100-300 字综述>",
    "unified_credit_code": "<统一社会信用代码或 null>",
    "registered_capital": "<注册资本或 null>",
    "main_business": "<主营业务一句话>",
    "controlling_shareholder": "<实际控制人或 null>",
    "listing_status": "<上市/非上市 + 板块或 null>",
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
    "solvency_analysis": "<偿债能力分析>",
    "profitability_analysis": "<盈利能力分析>",
    "cash_flow_analysis": "<现金流分析>",
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
    "operational_risks": [
      {"title": "<风险标题>", "description": "<描述>", "severity": "low|medium|high", "mitigations": ["<措施>"]}
    ],
    "financial_risks": [
      {"title": "<>", "description": "<>", "severity": "low|medium|high", "mitigations": []}
    ],
    "industry_risks": [
      {"title": "<>", "description": "<>", "severity": "low|medium|high", "mitigations": []}
    ],
    "compliance_risks": [
      {"title": "<>", "description": "<>", "severity": "low|medium|high", "mitigations": []}
    ],
    "overall_risk_level": "low|medium|high|very_high",
    "evidence": ["<chunk_id>"]
  },
  "credit_recommendation": {
    "narrative": "<200-400 字综合建议>",
    "decision": "approve|reject|approve_with_conditions",
    "recommended_credit_limit": "<建议额度或 null>",
    "recommended_term": "<建议期限或 null>",
    "recommended_rate_range": "<利率区间或 null>",
    "guarantee_requirements": ["<担保要求>"],
    "conditions": ["<附加条件,approve_with_conditions 时填>"],
    "evidence": ["<chunk_id>"]
  }
}

**约束**:
- evidence 里的 chunk_id 必须来自下方 Insights 中出现的数据(不要凭空构造)
- narrative 用规范中文金融术语
- 风险等级保守:有重大风险信号时建议 reject 或 approve_with_conditions
- 无 Insight 支撑的内容在 narrative 里声明"数据缺失,建议补充材料"
"""


def build_credit_report_prompt(state: ResearchState) -> str:
    insights_str = "\n".join(
        f"- [{i.subtask_id}] {i.finding}(confidence={i.confidence})" for i in state.insights
    )
    return (
        _SYSTEM_PROMPT
        + f"\n\n# Insights\n{insights_str}\n"
        + f"\n# 用户原始需求 / 信贷场景\n{state.user_message}\n"
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
            schema=CreditInvestigationReport,
            request_id=state.request_id,
        )
        if not isinstance(r.parsed, CreditInvestigationReport):
            raise RuntimeError(
                f"Writer expected CreditInvestigationReport from LLMService.chat(parsed=), "
                f"got {type(r.parsed).__name__}"
            )
        report = r.parsed
        # writer 覆盖 request_id 和 generated_at(LLM 输出值不可信)
        report = report.model_copy(
            update={
                "request_id": state.request_id,
                "generated_at": datetime.now(),
            }
        )

        markdown = render_credit_report_markdown(report)

        return StepResult(
            state_update={
                "credit_report": report,
                "report_markdown": markdown,  # 兼容老 SSE / 前端
                "chart_specs": [],  # v0.8.2 不做 chart;v0.8.5 加回
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
