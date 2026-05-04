"""Render PortfolioWarningReport → markdown(类比 investment_dd_renderer)."""

from __future__ import annotations

from app.agents.portfolio_warning_schema import PortfolioWarningReport
from app.services.monitoring.signal_rules.base import SignalLevel

_LEVEL_LABEL = {
    SignalLevel.GREEN: "🟢 绿色 (正常)",
    SignalLevel.YELLOW: "🟡 黄色 (警示)",
    SignalLevel.RED: "🔴 红色 (高危)",
}


def render_portfolio_warning_markdown(report: PortfolioWarningReport) -> str:
    lines: list[str] = []
    lines.append(f"# {report.customer_name} — 持仓预警报告")
    lines.append("")
    lines.append(f"- **客户**: {report.customer_name} ({report.ts_code})")
    lines.append(f"- **行业**: {report.industry}")
    lines.append(f"- **生成时间**: {report.generated_at.isoformat()}")
    lines.append(f"- **alert 等级**: {_LEVEL_LABEL[report.alert_level]}")
    lines.append("")
    lines.append("## 综述")
    lines.append("")
    lines.append(report.summary)
    lines.append("")

    if report.triggered_signals:
        lines.append("## 触发信号")
        lines.append("")
        lines.append("| 信号 | 等级 | 检测值 | 阈值 | 说明 |")
        lines.append("|---|---|---|---|---|")
        for s in report.triggered_signals:
            lines.append(
                f"| {s.rule_name} | {s.level.value} | {s.detected_value} | {s.threshold} | {s.explanation} |"
            )
        lines.append("")

    if report.risk_diagnosis:
        lines.append("## 风险诊断")
        lines.append("")
        lines.append(f"**严重度**: {report.risk_diagnosis.severity}")
        lines.append("")
        lines.append(report.risk_diagnosis.narrative)
        lines.append("")

    if report.deep_dive:
        lines.append("## 深度调查")
        lines.append("")
        lines.append(report.deep_dive.content)
        lines.append("")
        if report.deep_dive.evidence_chunk_ids:
            lines.append(f"_引用 chunk: {', '.join(report.deep_dive.evidence_chunk_ids)}_")
            lines.append("")

    if report.recommendations:
        lines.append("## 行动建议")
        lines.append("")
        for r in report.recommendations:
            lines.append(f"- {r}")
        lines.append("")

    if report.data_sources or report.data_limitations:
        lines.append("## 数据声明")
        lines.append("")
        if report.data_sources:
            lines.append(f"- 数据来源: {', '.join(report.data_sources)}")
        if report.data_limitations:
            for lim in report.data_limitations:
                lines.append(f"- 数据局限: {lim}")
        lines.append("")

    if report.references:
        lines.append("## 引用")
        lines.append("")
        for ref in report.references:
            url_part = f" [link]({ref.url})" if ref.url else ""
            lines.append(f"- **{ref.source}**{url_part}: {ref.snippet}")
        lines.append("")

    return "\n".join(lines)
