"""Writer — emits CreditInvestigationReport schema-conformant JSON (v0.8.2).

设计 ref: docs/superpowers/specs/2026-05-03-v0.8.2-credit-research-report-design.md § 3
"""

from __future__ import annotations

from datetime import datetime

from app.agents.base import Agent
from app.agents.credit_report_renderer import render_credit_report_markdown
from app.agents.credit_report_schema import CreditInvestigationReport
from app.agents.schemas import ResearchState, StepResult
from app.services.llm_response import Tier

_SYSTEM_PROMPT = """你是银行公司金融部 / 信贷研究分析师。

任务:基于已收集的 Insights + 用户提供的企业名 + 信贷场景,产出一份**信贷调查报告**(JSON 格式),
报告将作为信贷审批决策的依据。

报告结构(全部必填):
1. § 基本信息(CompanyOverview):企业基本信息,主营业务一句话
2. § 主体资格(LegalQualification):法律主体合规情况、经营资质、不良记录
3. § 财务分析(FinancialAnalysis):3-4 个关键财务指标 + 偿债 / 盈利 / 现金流三段分析
4. § 行业分析(IndustryAnalysis):所属行业、景气度、竞争地位、政策影响
5. § 风险评估(RiskAssessment):经营 / 财务 / 行业 / 合规四类风险 + 整体等级
6. § 信贷建议(CreditRecommendation):决策建议(批准 / 拒绝 / 有条件批准) + 额度 / 期限 / 利率 / 担保

**强制要求**:
- 每个 section 必须填 evidence 字段(chunk_id 列表,至少 1 个)
- 所有 narrative 用规范中文金融术语(资产负债率 / 经营性现金流 / 不良贷款率 等)
- 风险等级和决策建议要保守:有重大风险信号时建议 reject 或 approve_with_conditions
- 数据来自 Insights / KB / Web 搜索,无依据的结论不要编造,在 narrative 里诚实声明 limitation

输出符合 CreditInvestigationReport schema 的 JSON,**不要**输出 markdown / 解释 / 多余文字。
"""


def build_credit_report_prompt(state: ResearchState) -> str:
    insights_str = "\n".join(
        f"- [{i.subtask_id}] {i.finding}(confidence={i.confidence})" for i in state.insights
    )
    return (
        _SYSTEM_PROMPT
        + f"\n\n# Insights\n{insights_str}\n"
        + f"\n# 用户原始需求 / 信贷场景\n{state.user_message}\n"
        + "\n请按 schema 输出 JSON。"
    )


class Writer(Agent):
    name = "Writer"
    model_tier: Tier = "balanced"

    def step(self, state: ResearchState) -> StepResult:  # type: ignore[override]
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
