"""DEPRECATED in v1.x — superseded by plan_template.py + plan_validator.py.

The v0.8.5 4-plan constrained-router (capital_preservation / stable_growth /
balanced / aggressive_growth) is replaced by a single DD_PLAN_TEMPLATE +
Validator gate. This module is kept as archive; no live code path imports it.
Will be removed after v1.x stable.

spec ref: docs/superpowers/specs/2026-05-15-v1.x-plan-template-validator-design.md § 12
"""

from __future__ import annotations

from app.agents.schemas import PlanId, Subtask, SubtaskTemplate

__all__ = ["PLAN_REGISTRY", "instantiate_plan"]

PLAN_REGISTRY: dict[PlanId, list[SubtaskTemplate]] = {
    "capital_preservation": [
        SubtaskTemplate(
            description_template=(
                "评估 {target_name}({ts_code}) 偿债能力 — 资产负债率 / 流动比 / 经营现金流覆盖"
            ),
            rationale="capital_preservation 客户最担心爆雷, 偿债是底线",
            required_tools=("get_balance_sheet", "get_cashflow", "get_financials"),
        ),
        SubtaskTemplate(
            description_template=(
                "评估 {target_name}({ts_code}) 现金流质量 — 经营现金流/净利润比 + 自由现金流"
            ),
            rationale="盈利质量校验 — 利润真实变现能力, 防虚胖利润",
            required_tools=("get_cashflow", "get_financials"),
        ),
        SubtaskTemplate(
            description_template=(
                "评估 {target_name}({ts_code}) 估值水平 — PE 历史分位 + 行业对比"
            ),
            rationale="保本型避免高估值买入, PE 历史分位 < 50% 才入场",
            required_tools=("get_pe_history", "get_daily_basic"),
        ),
        SubtaskTemplate(
            description_template=(
                "评估 {target_name}({ts_code}) 风险因素 — 大股东减持 / 质押率 / 限售解禁"
            ),
            rationale="保本型对治理风险零容忍",
            required_tools=("get_holder_change", "kb_search", "web_search"),
        ),
    ],
    "stable_growth": [
        SubtaskTemplate(
            description_template=(
                "评估 {target_name}({ts_code}) 盈利能力稳定性 — ROE 5 年趋势 + 毛利率"
            ),
            rationale="stable_growth 看 ROE 稳健而非爆发力",
            required_tools=("get_financials",),
        ),
        SubtaskTemplate(
            description_template=(
                "评估 {target_name}({ts_code}) 分红历史 — 5 年分红连续性 + 股息率"
            ),
            rationale="stable_growth 重视股息收益作为持仓回报",
            required_tools=("get_dividend_history", "get_daily_basic"),
        ),
        SubtaskTemplate(
            description_template=("评估 {target_name}({ts_code}) 行业地位 — 申万分位 + 市占率"),
            rationale="行业龙头才有稳定性, stable_growth 偏好龙头",
            required_tools=("web_search", "kb_search"),
        ),
        SubtaskTemplate(
            description_template=(
                "评估 {target_name}({ts_code}) 偿债基础 — 资产负债率不高于行业均值"
            ),
            rationale="稳健增长前提是财务结构健康",
            required_tools=("get_balance_sheet", "get_financials"),
        ),
    ],
    "balanced": [
        SubtaskTemplate(
            description_template=(
                "评估 {target_name}({ts_code}) 财务健康度 — ROE / 毛利率 / 资产负债率综合"
            ),
            rationale="balanced 客户需要全面财务画像",
            required_tools=("get_financials", "get_balance_sheet"),
        ),
        SubtaskTemplate(
            description_template=("评估 {target_name}({ts_code}) 估值水平 — PE / PB / 历史分位"),
            rationale="估值合理是 balanced 配置基本要求",
            required_tools=("get_daily_basic", "get_pe_history"),
        ),
        SubtaskTemplate(
            description_template=(
                "评估 {target_name}({ts_code}) 行业地位 + 短期催化 — 业绩预告 / 行业新闻"
            ),
            rationale="balanced 关注成长性 + 行业周期",
            required_tools=("get_forecast", "get_news", "web_search"),
        ),
        SubtaskTemplate(
            description_template=(
                "评估 {target_name}({ts_code}) 风险因素 — 治理 / 政策 / 短期资金动向"
            ),
            rationale="balanced 不偏废风险评估",
            required_tools=("get_money_flow", "kb_search", "get_holder_change"),
        ),
    ],
    "aggressive_growth": [
        SubtaskTemplate(
            description_template=(
                "评估 {target_name}({ts_code}) 成长性 — 营收/净利同比 + 业绩预告"
            ),
            rationale="aggressive_growth 第一看高速成长",
            required_tools=("get_financials", "get_forecast"),
        ),
        SubtaskTemplate(
            description_template=("评估 {target_name}({ts_code}) 估值空间 — PE 历史分位 + PEG"),
            rationale="高成长股需 PE 仍有空间, PEG < 1.5",
            required_tools=("get_pe_history", "get_daily_basic"),
        ),
        SubtaskTemplate(
            description_template=(
                "评估 {target_name}({ts_code}) 行业赛道 + 政策催化 — 申万 + 概念 + 政策"
            ),
            rationale="aggressive_growth 押注赛道而非个股",
            required_tools=("web_search", "get_news", "kb_search"),
        ),
        SubtaskTemplate(
            description_template=(
                "评估 {target_name}({ts_code}) 短期资金博弈 — 龙虎榜 / 大单流入 / 散户化"
            ),
            rationale="aggressive_growth 看短期资金动向决定入场点",
            required_tools=("get_money_flow", "get_holder_change"),
        ),
    ],
}


def instantiate_plan(plan_id: PlanId, target_name: str, ts_code: str) -> list[Subtask]:
    """Instantiate a Subtask list from PLAN_REGISTRY for a concrete target.

    Pure function — same input always yields the same output. The
    ``subtask_id`` is generated as ``f"{plan_id}_{idx}"`` so identifiers are
    stable across calls for the same ``plan_id``.

    Args:
        plan_id: Which plan template to expand. Must be one of the 4 keys
            in :data:`PLAN_REGISTRY`.
        target_name: Human-readable company name (e.g. "贵州茅台").
        ts_code: Tushare stock code (e.g. "600519.SH").

    Returns:
        Concrete ``list[Subtask]`` ready for downstream agents.
    """
    templates = PLAN_REGISTRY[plan_id]
    return [
        Subtask(
            subtask_id=f"{plan_id}_{idx}",
            description=tmpl.description_template.format(target_name=target_name, ts_code=ts_code),
            rationale=tmpl.rationale,
            required_tools=list(tmpl.required_tools),
        )
        for idx, tmpl in enumerate(templates)
    ]
