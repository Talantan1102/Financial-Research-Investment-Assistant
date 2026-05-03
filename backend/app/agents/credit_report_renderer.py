"""信贷调查报告 Pydantic schema → markdown 渲染器。

设计 ref: docs/superpowers/specs/2026-05-03-v0.8.2-credit-research-report-design.md § 2.4
"""

from __future__ import annotations

from app.agents.credit_report_schema import (
    CreditInvestigationReport,
    FinancialMetric,
    RiskItem,
)

_DECISION_ZH: dict[str, str] = {
    "approve": "批准",
    "reject": "拒绝",
    "approve_with_conditions": "有条件批准",
}

_RISK_LEVEL_ZH: dict[str, str] = {
    "low": "低",
    "medium": "中",
    "high": "高",
    "very_high": "极高",
}

_SEVERITY_ZH: dict[str, str] = {"low": "低", "medium": "中", "high": "高"}


def _render_evidence(chunk_ids: list[str]) -> str:
    if not chunk_ids:
        return ""
    items = " · ".join(f"`{cid}`" for cid in chunk_ids)
    return f"\n> **引用**:{items}\n"


def _render_metric_table(metrics: list[FinancialMetric]) -> str:
    if not metrics:
        return "_暂无关键财务指标_\n"
    lines = ["| 指标 | 期间 | 数值 | 同比 |", "|---|---|---|---|"]
    for m in metrics:
        yoy = m.yoy_change if m.yoy_change else "—"
        lines.append(f"| {m.name} | {m.period} | {m.value} | {yoy} |")
    return "\n".join(lines) + "\n"


def _render_risk_items(items: list[RiskItem], category: str) -> str:
    if not items:
        return f"- _{category}:无_\n"
    out: list[str] = [f"### {category}"]
    for ri in items:
        sev = _SEVERITY_ZH.get(ri.severity, ri.severity)
        out.append(f"- **{ri.title}**(严重度:{sev}) — {ri.description}")
        if ri.mitigations:
            mits = " / ".join(ri.mitigations)
            out.append(f"  缓释措施:{mits}")
    return "\n".join(out) + "\n"


def render_credit_report_markdown(r: CreditInvestigationReport) -> str:  # noqa: PLR0915
    parts: list[str] = []

    # Header
    parts.append(f"# 信贷调查报告 — {r.company_name}\n")
    parts.append(f"_生成时间:{r.generated_at.isoformat()} · request_id:`{r.request_id}`_\n")

    # § 1 CompanyOverview
    co = r.company_overview
    parts.append("## § 1 基本信息\n")
    parts.append(f"{co.narrative}\n")
    if co.unified_credit_code:
        parts.append(f"- 统一社会信用代码:{co.unified_credit_code}")
    if co.registered_capital:
        parts.append(f"- 注册资本:{co.registered_capital}")
    parts.append(f"- 主营业务:{co.main_business}")
    if co.controlling_shareholder:
        parts.append(f"- 实际控制人:{co.controlling_shareholder}")
    if co.listing_status:
        parts.append(f"- 上市情况:{co.listing_status}")
    parts.append(_render_evidence(co.evidence))

    # § 2 LegalQualification
    lq = r.legal_qualification
    parts.append("## § 2 主体资格\n")
    parts.append(f"{lq.narrative}\n")
    parts.append(f"- 法律主体:{lq.legal_status}")
    if lq.business_qualifications:
        parts.append("- 经营资质:")
        for q in lq.business_qualifications:
            parts.append(f"  - {q}")
    if lq.adverse_records:
        parts.append("- 不良记录:")
        for a in lq.adverse_records:
            parts.append(f"  - {a}")
    else:
        parts.append("- 不良记录:无")
    parts.append(_render_evidence(lq.evidence))

    # § 3 FinancialAnalysis
    fa = r.financial_analysis
    parts.append("## § 3 财务分析\n")
    parts.append(f"{fa.narrative}\n")
    parts.append("### 关键财务指标\n")
    parts.append(_render_metric_table(fa.key_metrics))
    parts.append(f"### 偿债能力\n{fa.solvency_analysis}\n")
    parts.append(f"### 盈利能力\n{fa.profitability_analysis}\n")
    parts.append(f"### 现金流分析\n{fa.cash_flow_analysis}\n")
    if fa.year_over_year_summary:
        parts.append(f"### 同比变化\n{fa.year_over_year_summary}\n")
    parts.append(_render_evidence(fa.evidence))

    # § 4 IndustryAnalysis
    ia = r.industry_analysis
    parts.append("## § 4 行业分析\n")
    parts.append(f"{ia.narrative}\n")
    parts.append(f"- 所属行业:{ia.industry_name}")
    parts.append(f"- 景气度:{ia.industry_outlook}")
    parts.append(f"- 竞争地位:{ia.competitive_position}")
    if ia.key_competitors:
        comps = " / ".join(ia.key_competitors)
        parts.append(f"- 主要竞争对手:{comps}")
    parts.append(f"- 政策影响:{ia.policy_impact}")
    parts.append(_render_evidence(ia.evidence))

    # § 5 RiskAssessment
    ra = r.risk_assessment
    parts.append("## § 5 风险评估\n")
    parts.append(f"{ra.narrative}\n")
    parts.append(
        f"**整体风险等级:{_RISK_LEVEL_ZH.get(ra.overall_risk_level, ra.overall_risk_level)}**\n"
    )
    parts.append(_render_risk_items(ra.operational_risks, "经营风险"))
    parts.append(_render_risk_items(ra.financial_risks, "财务风险"))
    parts.append(_render_risk_items(ra.industry_risks, "行业风险"))
    parts.append(_render_risk_items(ra.compliance_risks, "合规风险"))
    parts.append(_render_evidence(ra.evidence))

    # § 6 CreditRecommendation
    cr = r.credit_recommendation
    parts.append("## § 6 信贷建议\n")
    parts.append(f"{cr.narrative}\n")
    decision_zh = _DECISION_ZH.get(cr.decision, cr.decision)
    parts.append(f"**决策建议:{decision_zh}**\n")
    if cr.recommended_credit_limit:
        parts.append(f"- 建议额度:{cr.recommended_credit_limit}")
    if cr.recommended_term:
        parts.append(f"- 建议期限:{cr.recommended_term}")
    if cr.recommended_rate_range:
        parts.append(f"- 建议利率区间:{cr.recommended_rate_range}")
    if cr.guarantee_requirements:
        parts.append("- 担保要求:")
        for g in cr.guarantee_requirements:
            parts.append(f"  - {g}")
    if cr.conditions:
        parts.append("- 附加条件:")
        for c in cr.conditions:
            parts.append(f"  - {c}")
    parts.append(_render_evidence(cr.evidence))

    return "\n".join(parts)
