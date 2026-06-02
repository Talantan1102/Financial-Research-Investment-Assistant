"""投资标的尽调报告 schema → markdown 渲染器 (v0.8.4).

设计 ref: docs/superpowers/specs/2026-05-04-v0.8.4-b1-single-deep-design.md § 3
"""

from __future__ import annotations

from app.agents.investment_dd_schema import (
    FinancialMetric,
    InvestmentDueDiligenceReport,
    RiskItem,
)

_RECOMMENDATION_ZH: dict[str, str] = {
    "recommend_buy": "买入",
    "recommend_overweight": "增持",
    "recommend_hold": "持有",
    "recommend_underweight": "减持",
    "recommend_sell": "卖出",
}

_RISK_LEVEL_ZH: dict[str, str] = {
    "low": "低",
    "medium": "中",
    "high": "高",
    "very_high": "极高",
}

_SEVERITY_ZH: dict[str, str] = {"low": "低", "medium": "中", "high": "高"}

_HOLDING_PERIOD_ZH: dict[str, str] = {
    "short_term": "短期(<6个月)",
    "medium_term": "中期(6-24个月)",
    "long_term": "长期(>24个月)",
}


def _render_evidence_footnotes(chunk_ids: list[str]) -> tuple[str, list[str]]:
    """Returns (inline_refs_str, footnote_definitions_list).

    Inline refs: [^chunk_id_1][^chunk_id_2]...
    Footnote defs: ["[^chunk_id_1]: chunk_id_1", ...]
    """
    if not chunk_ids:
        return "", []
    inline = "".join(f"[^{cid}]" for cid in chunk_ids)
    defs = [f"[^{cid}]: {cid}" for cid in chunk_ids]
    return inline, defs


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


def render_investment_dd_report_markdown(  # noqa: PLR0915
    report: InvestmentDueDiligenceReport,
) -> str:
    """Render InvestmentDueDiligenceReport as markdown string.

    Layout:
    - Top: disclaimer > ⚠️ ... block
    - Header: # 投资标的尽调报告 — {target_name} ({target_ts_code})
    - Meta: generated_at / request_id
    - § 1 ~ § 6 sections with ## § N title
    - Evidence inline footnotes [^chunk_id] per section
    - Bottom: footnote definitions list + disclaimer footer
    """
    parts: list[str] = []
    all_footnote_defs: list[str] = []

    # Top disclaimer block
    parts.append(f"> ⚠️ {report.disclaimer}\n")

    # Header
    parts.append(f"# 投资标的尽调报告 — {report.target_name} ({report.target_ts_code})\n")
    parts.append(
        f"_生成时间:{report.generated_at.isoformat()} · request_id:`{report.request_id}`_\n"
    )

    # § 1 TargetOverview
    to = report.target_overview
    inline_refs, defs = _render_evidence_footnotes(to.evidence)
    all_footnote_defs.extend(defs)
    parts.append("## § 1 标的基本信息\n")
    parts.append(f"{to.narrative}{inline_refs}\n")
    if to.registered_capital:
        parts.append(f"- 注册资本:{to.registered_capital}")
    parts.append(f"- 主营业务:{to.main_business}")
    if to.controlling_shareholder:
        parts.append(f"- 实际控制人:{to.controlling_shareholder}")
    if to.listing_status:
        parts.append(f"- 上市情况:{to.listing_status}")
    # Valuation snapshot
    val_items: list[str] = []
    if to.current_pe is not None:
        val_items.append(f"PE:{to.current_pe:.1f}x")
    if to.current_pb is not None:
        val_items.append(f"PB:{to.current_pb:.2f}x")
    if to.current_market_cap is not None:
        val_items.append(f"总市值:{to.current_market_cap:.0f}亿元")
    if to.dividend_yield is not None:
        val_items.append(f"股息率:{to.dividend_yield:.2f}%")
    if val_items:
        parts.append(f"- 估值快照:{' / '.join(val_items)}")

    # § 2 LegalQualification
    lq = report.legal_qualification
    inline_refs, defs = _render_evidence_footnotes(lq.evidence)
    all_footnote_defs.extend(defs)
    parts.append("\n## § 2 主体资格\n")
    parts.append(f"{lq.narrative}{inline_refs}\n")
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

    # § 3 FinancialAnalysis
    fa = report.financial_analysis
    inline_refs, defs = _render_evidence_footnotes(fa.evidence)
    all_footnote_defs.extend(defs)
    parts.append("\n## § 3 财务分析\n")
    parts.append(f"{fa.narrative}{inline_refs}\n")
    parts.append("### 关键财务指标\n")
    parts.append(_render_metric_table(fa.key_metrics))
    parts.append(f"### 盈利质量\n{fa.profitability_analysis}\n")
    parts.append(f"### 成长性\n{fa.growth_analysis}\n")
    parts.append(f"### 投资回报\n{fa.return_analysis}\n")
    parts.append(f"### 现金流\n{fa.cash_flow_analysis}\n")
    # Valuation analysis sub-section
    va = fa.valuation_analysis
    parts.append(f"### 估值分析\n{va.narrative}\n")
    val_detail: list[str] = []
    if va.pe_historical_percentile:
        val_detail.append(f"- PE 历史百分位:{va.pe_historical_percentile}")
    if va.dcf_valuation:
        val_detail.append(f"- DCF 估值:{va.dcf_valuation}")
    if va.peer_comparison:
        val_detail.append(f"- 同业对比:{va.peer_comparison}")
    if val_detail:
        parts.extend(val_detail)
    if fa.year_over_year_summary:
        parts.append(f"### 同比变化\n{fa.year_over_year_summary}\n")

    # § 4 IndustryAnalysis
    ia = report.industry_analysis
    inline_refs, defs = _render_evidence_footnotes(ia.evidence)
    all_footnote_defs.extend(defs)
    parts.append("\n## § 4 行业分析\n")
    parts.append(f"{ia.narrative}{inline_refs}\n")
    parts.append(f"- 所属行业:{ia.industry_name}")
    parts.append(f"- 景气度:{ia.industry_outlook}")
    parts.append(f"- 竞争地位:{ia.competitive_position}")
    if ia.key_competitors:
        comps = " / ".join(ia.key_competitors)
        parts.append(f"- 主要竞争对手:{comps}")
    parts.append(f"- 政策影响:{ia.policy_impact}")

    # § 5 RiskAssessment
    ra = report.risk_assessment
    inline_refs, defs = _render_evidence_footnotes(ra.evidence)
    all_footnote_defs.extend(defs)
    parts.append("\n## § 5 风险评估\n")
    parts.append(f"{ra.narrative}{inline_refs}\n")
    parts.append(
        f"**整体风险等级:{_RISK_LEVEL_ZH.get(ra.overall_risk_level, ra.overall_risk_level)}**\n"
    )
    parts.append(_render_risk_items(ra.market_risk, "市场风险"))
    parts.append(_render_risk_items(ra.growth_risk, "成长风险"))
    parts.append(_render_risk_items(ra.event_risk, "事件风险"))
    parts.append(_render_risk_items(ra.valuation_risk, "估值风险"))

    # § 6 InvestmentRecommendation
    ir = report.investment_recommendation
    inline_refs, defs = _render_evidence_footnotes(ir.evidence)
    all_footnote_defs.extend(defs)
    parts.append("\n## § 6 投资建议\n")
    parts.append(f"{ir.narrative}{inline_refs}\n")
    rec_zh = _RECOMMENDATION_ZH.get(ir.recommendation, ir.recommendation)
    parts.append(f"**投资建议:{rec_zh}**\n")
    parts.append(f"- 建议仓位:{ir.recommended_position_size_pct:.1f}% of AUM")
    period_zh = _HOLDING_PERIOD_ZH.get(ir.recommended_holding_period, ir.recommended_holding_period)
    parts.append(f"- 建议持有期:{period_zh}")
    parts.append(
        f"- 建议买入价格区间:{ir.recommended_entry_price_range.low:.2f} ~ "
        f"{ir.recommended_entry_price_range.high:.2f}"
    )
    parts.append(f"- 止损价格:{ir.recommended_stop_loss_price:.2f}")
    parts.append(
        f"- 目标价格区间(estimated):{ir.estimated_target_price_range.low:.2f} ~ "
        f"{ir.estimated_target_price_range.high:.2f}"
    )
    if ir.position_management_conditions:
        parts.append("- 仓位管理条件:")
        for cond in ir.position_management_conditions:
            parts.append(f"  - {cond}")

    # Footnotes — C48: dedup by preserving first-occurrence order so a chunk_id
    # cited in multiple sections produces exactly one [^id]: definition.
    if all_footnote_defs:
        parts.append("\n---\n")
        parts.append("**引用来源**\n")
        parts.extend(dict.fromkeys(all_footnote_defs))

    # Bottom footer disclaimer
    parts.append(f"\n---\n\n> ⚠️ **免责声明**: {report.disclaimer}\n")

    return "\n".join(parts)
