"""Writer — emits InvestmentDueDiligenceReport schema-conformant JSON (v0.8.4).

v0.8.3: adds alert_writer mode — when state.mode == "alert_deep_dive" the writer
produces a PortfolioWarningReport instead of an InvestmentDueDiligenceReport.

v0.8.4: build_investment_dd_prompt is conditioned on the 6 input fields. 去推荐
改造(2026-06-04)后,investment_objective / horizon / risk_tolerance / aum /
existing_position 只用于校准 § 6 综合研判的"研究重心"(多空侧重、关键判断变量),
不再驱动评级 / 仓位 / 止损;target_ts_code 仍为全局 data anchor。

去推荐改造: § 6 由 InvestmentRecommendation(评级/仓位/目标价)改为
InvestmentSynthesis(综合研判:多空两面 + 估值背景,不下买卖结论)。
post_process_writer_output 不再覆盖评级/仓位,仅保留 A5a 估值 cross-check 覆盖
+ A5b 多空辩论注入。推荐引擎脚本(classify_recommendation /
compute_position_size_pct)已下线。

spec ref: docs/superpowers/specs/2026-05-04-v0.8.4-b1-single-deep-design.md § 3 / § 5.3
spec ref: docs/superpowers/specs/2026-05-04-v0.8.5-constrained-router-design.md § Task 5
spec ref: docs/superpowers/plans/2026-05-05-v0.8.5-constrained-router-implementation.md § Task 9
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from app.agents.base import Agent
from app.agents.investment_dd_renderer import render_investment_dd_report_markdown
from app.agents.investment_dd_schema import InvestmentDueDiligenceReport
from app.agents.portfolio_warning_schema import PortfolioWarningReport
from app.agents.schemas import ResearchState, StepResult
from app.services.llm_response import Tier
from app.skills.financial_research import _SOP_TEXT  # C62: single SSOT for SOP text

# ---------------------------------------------------------------------------
# Investment-objective–specific § 6 research-focus framing blocks
# 去推荐后:只校准"研究重心"(多空侧重 / 关键判断变量),不再产出评级/仓位/止损。
# ---------------------------------------------------------------------------

_OBJECTIVE_SECTION6_GUIDANCE: dict[str, str] = {
    "capital_preservation": (
        "客户投资目标为 capital_preservation(保本保值):§ 6 综合研判应把研究重心放在下行风险与本金安全——"
        "bear_case(下行情形 / 估值过高风险 / 回撤可能)必须充分呈现;"
        "key_judgment_factors 应突出'什么情况下本金会受损'。"
        "narrative 必须明确提及 capital_preservation 目标,但**不得**给出买卖评级 / 目标价 / 建议仓位 / 止损位。"
    ),
    "stable_growth": (
        "客户投资目标为 stable_growth(稳健增长):§ 6 综合研判应兼顾增长驱动与风险防御——"
        "bull_case 与 bear_case 均衡呈现,key_judgment_factors 覆盖'增长能否持续'与'主要下行变量'。"
        "narrative 必须明确提及 stable_growth 目标,但**不得**给出买卖评级 / 目标价 / 建议仓位。"
    ),
    "balanced": (
        "客户投资目标为 balanced(均衡配置):§ 6 综合研判应对等呈现多空两面——"
        "bull_case 与 bear_case 篇幅相当,key_judgment_factors 兼顾成长与防御。"
        "narrative 必须明确提及 balanced 均衡配置目标,但**不得**给出买卖评级 / 目标价 / 建议仓位。"
    ),
    "aggressive_growth": (
        "客户投资目标为 aggressive_growth(激进成长):§ 6 综合研判应把研究重心放在成长弹性与驱动因素——"
        "bull_case(成长驱动 / 行业空间 / 弹性来源)充分呈现,但仍须客观给出 bear_case(系统性 / 行业颠覆风险);"
        "key_judgment_factors 突出'成长能否兑现'。"
        "narrative 必须明确提及 aggressive_growth 目标,但**不得**给出买卖评级 / 目标价 / 建议仓位。"
    ),
}


def _format_user_preferences(state: ResearchState) -> str:
    """Return a formatted preference block for the prompt, or empty string.

    v0.9 — when chat_extracted_preferences is non-empty, injects a section
    that instructs the LLM to honor user-expressed preferences (horizon,
    risk_tolerance, etc.) in the § 6 综合研判 narrative.
    """
    if not state.chat_extracted_preferences:
        return ""
    lines = ["\n【用户在 chat 表达的偏好 (投资建议必须 honor)】"]
    for p in state.chat_extracted_preferences:
        lines.append(f"- [{p.category}] {p.text}  (置信度 {p.confidence:.2f})")
    return "\n".join(lines)


def _format_cross_check_block(state: ResearchState) -> str:
    """v1.x A5a: 根据 state.valuation_analysis 状态产生 narrative 引用约束 block.

    valuation_analysis=None → return ""(LLM 自由写,跟 v0.8.5 一样)
    consistency=consistent  → 提醒 narrative 提及一致性
    consistency=moderate    → 提醒 narrative 解释偏离原因
    consistency=severe + diagnosis exists → 提醒 narrative 显式引用 diagnosis.narrative
    consistency=severe + diagnosis None   → 提醒 narrative flag 诊断不确定

    spec ref: 2026-05-16-v1.x-multi-valuation-cross-check-design.md § 9.2
    """
    va = state.valuation_analysis
    if va is None or va.valuation_consistency is None:
        return ""

    # 收集激活的 lens 数字给 LLM context
    vals_lines: list[str] = []
    if va.pe_value is not None:
        vals_lines.append(f"  - PE: {va.pe_value:,.2f}")
    if va.pb_value is not None:
        vals_lines.append(f"  - PB: {va.pb_value:,.2f}")
    if va.ev_ebitda_value is not None:
        vals_lines.append(f"  - EV/EBITDA: {va.ev_ebitda_value:,.2f}")
    if va.dcf_base is not None:
        vals_lines.append(f"  - DCF base: {va.dcf_base:,.2f}")
    if va.dcf_bull is not None:
        vals_lines.append(f"  - DCF bull: {va.dcf_bull:,.2f}")
    if va.dcf_bear is not None:
        vals_lines.append(f"  - DCF bear: {va.dcf_bear:,.2f}")
    vals_block = "\n".join(vals_lines) if vals_lines else "  (无有效 lens 数据)"

    header = (
        f"\n\n# v1.x A5a cross-check 约束(Critic 第 7 维 valuation_consistency 守护)\n"
        f"多模型估值结果 ({va.valuation_consistency}):\n"
        f"{vals_block}\n"
    )

    if va.valuation_consistency == "consistent":
        return (
            header
            + "**§ 估值 narrative 要求**:多个 lens 信号一致,narrative 应用 '一致 / 吻合 / 趋同' "
            + "等词显式说明 cross-check 收敛,给读者 confidence。\n"
        )

    if va.valuation_consistency == "moderate":
        return (
            header
            + "**§ 估值 narrative 要求**:lens 存在 15-30% 偏离,narrative 必须用 "
            + "'偏离 / 差异 / 偏低 / 偏高 / 不一致' 等词显式解释偏离原因(行业周期 / 业务模式特点等)。\n"
        )

    # severe
    if va.outlier_diagnosis is not None:
        d = va.outlier_diagnosis
        return (
            header
            + "\n**Outlier 诊断**(由 OutlierDiagnosisAgent 产出):\n"
            + f"- outlier_model: {d.outlier_model.value}\n"
            + f"- likely_cause: {d.likely_cause}\n"
            + f"- confidence: {d.confidence}\n"
            + f"- recommended_action: {d.recommended_action}\n"
            + f"- diagnosis narrative: {d.narrative}\n\n"
            + "**§ 估值 narrative 要求**:cross-check 严重打架(>30% CV),narrative 必须"
            + f"**显式包含**上面的 diagnosis narrative 全文('{d.narrative}')"
            + "。禁止掩饰 / 平均化打架。打架本身是 signal,不是 bug。\n"
        )

    # severe but no diagnosis
    return (
        header
        + "**§ 估值 narrative 要求**:cross-check 严重打架但 OutlierDiagnosisAgent 未产出诊断 "
        + "(LLM 失败 fallback);narrative 必须用 '无法诊断' / '不确定' 等词显式 flag,"
        + "建议人工 review。禁止隐藏 cross-check 不一致信号。\n"
    )


def _format_debate_block(state: ResearchState) -> str:
    """v1.x A5b: 根据 state.debate_trace 产 narrative 引用约束 block。

    debate_trace=None → "" (LLM 自由写, 跟 v0.8.5 一样)
    rounds_completed=2 → 用 v2 (final 对抗后)
    rounds_completed=1 → 用 v1 (round 2 失败 fallback)

    spec ref: 2026-05-16-v1.x-bull-bear-debate-design.md § 8
    """
    trace = state.debate_trace
    if trace is None:
        return ""

    if trace.rounds_completed == 2:
        bull = trace.bull_v2
        bear = trace.bear_v2
        version = "v2 (round 2 后 final)"
    else:
        bull = trace.bull_v1
        bear = trace.bear_v1
        version = "v1 (round 2 失败 fallback)"

    if bull is None or bear is None:
        return ""

    bull_block = "\n".join(f"  - {a}" for a in bull.arguments)
    bear_block = "\n".join(f"  - {a}" for a in bear.arguments)

    return (
        f"\n\n# v1.x A5b debate cross-check 约束(Critic 第 8 维 dialectical_balance 守护)\n"
        f"Bull/Bear advocate {version} 论据:\n\n"
        f"看多 (Bull):\n{bull_block}\n"
        f"  strongest: {bull.strongest_argument}\n\n"
        f"看空 (Bear):\n{bear_block}\n"
        f"  strongest: {bear.strongest_argument}\n\n"
        f"**§ 6 综合研判 narrative 要求**:必须显式列举 **≥ 2 条 bull arguments + ≥ 2 条 bear arguments**;\n"
        f"必须基于 strongest_bull + strongest_bear 综合呈现两面研判(**不下买卖结论**)。**禁止只挑一面之词**\n"
        f"(打架 = signal, narrative 必须诚实双向论证)。\n"
    )


def _build_section6_constraint_block(state: ResearchState) -> str:
    """Build § 6 综合研判 constraint block conditioned on client context.

    去推荐改造:客户背景只用于校准研究重心(bull/bear 侧重、关键判断变量),
    不再驱动仓位 / 止损 / 目标价等 prescriptive 数字。
    """
    objective = state.investment_objective or "balanced"
    risk_tolerance = state.risk_tolerance or "moderate"
    investment_horizon = state.investment_horizon or "medium_term"
    client_total_aum = state.client_total_aum or 0.0
    existing_position = state.client_existing_position

    objective_block = _OBJECTIVE_SECTION6_GUIDANCE.get(
        objective, _OBJECTIVE_SECTION6_GUIDANCE["balanced"]
    )

    existing_str = (
        f"- client_existing_position(现有持仓): {existing_position:,.0f} CNY"
        if existing_position is not None
        else "- client_existing_position: 无现有持仓"
    )

    return f"""
## § 6 综合研判约束(必须严格遵守)

**客户背景**(仅用于校准研究重心,**不**用于生成买卖指令):
- investment_objective: {objective}
- investment_horizon: {investment_horizon}
- risk_tolerance: {risk_tolerance}
- client_total_aum(客户总资产管理规模): {client_total_aum:,.0f} CNY
{existing_str}

**研究重心指令**:
{objective_block}

**去推荐硬约束**:
- § 6 是"综合研判":呈现多空两面(bull_case / bear_case)+ 估值背景(valuation_context)+ 关键判断变量(key_judgment_factors)。
- **禁止**输出买卖评级 / 建议仓位 / 目标价 / 建议入场价 / 止损位 / 加减仓触发条件。
- valuation_context 只描述"当前价相对 § 3 内在价值区间的位置"(呼应估值,非目标价建议)。
- 关键判断变量留给读者自行决策,不替客户下结论。
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
      "pe_historical_percentile_value": null,
      "dcf_valuation": "<DCF 估值或 null>",
      "peer_comparison": "<同业估值对比或 null>"
    },
    "debt_ratio_assessment": null,
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
  "investment_synthesis": {
    "narrative": "<200-400 字综合研判:综合投资逻辑与估值背景,不给买卖评级/目标价/仓位>",
    "key_judgment_factors": ["<影响判断的关键变量,留给读者自行决策>"],
    "valuation_context": "<呼应 § 3 估值区间的研判,如'当前价位于内在价值区间下沿',或 null>",
    "bull_case": ["<看多论据>"],
    "bear_case": ["<看空论据>"],
    "strongest_bull_point": "<最强看多点或 null>",
    "strongest_bear_point": "<最强看空点或 null>",
    "evidence": ["<chunk_id>"]
  }
}

**通用约束**:
- evidence 里的 chunk_id 必须来自下方 Insights 中出现的数据(不要凭空构造)
- narrative 用规范中文金融术语
- 风险等级客观评估:有重大风险信号时 overall_risk_level 选 high 或 very_high
- 无 Insight 支撑的内容在 narrative 里声明"数据缺失,建议补充材料"

**v0.8.5 数值化字段(若可量化必须同时填,以便后端决定论 helper 使用)**:
- ``financial_analysis.valuation_analysis.pe_historical_percentile_value``: float in [0.0, 1.0],
  例如近 5 年 PE 30 分位 → 0.30。无法判断时填 null,narrative 中说明数据缺失。
- ``financial_analysis.debt_ratio_assessment``: 必须从 {"健康", "一般", "警戒", "高风险"} 中四选一
  (资产负债率<30% → 健康;30-50% → 一般;50-70% → 警戒;>70% → 高风险);数据缺失时填 null。
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

    # v0.9 — chat preference block (empty string when no preferences).
    preference_block = _format_user_preferences(state)

    # v1.x A5a — cross-check constraint block (empty string when no valuation_analysis
    # or valuation_consistency is None). Injects lens numbers + narrative rules so the
    # LLM can correctly reference outlier diagnosis / consistency signal.
    cross_check_block = _format_cross_check_block(state)

    # v1.x A5b — debate cross-check block (empty string when no debate_trace).
    # Injects bull/bear final arguments + narrative bidirectional requirement.
    debate_block = _format_debate_block(state)

    # v1.x — Critic factuality feedback for writer retry path (spec § 7.2 / Task 1.9).
    # When ResearchState.writer_critic_feedback is set (populated by
    # writer_retry_transition node when factuality < 7.0), inject a feedback
    # block instructing the LLM to fix evidence/chunk_id issues on retry.
    feedback_block = ""
    if state.writer_critic_feedback:
        feedback_block = (
            f"\n# Critic 反馈(上一轮 factuality 评分低,需重写以修正)\n"
            f"{state.writer_critic_feedback}\n"
            f"→ 检查证据引用,修正不准确表述,确保 evidence chunk_id 真实存在。"
            f"避免编造数据点或引用不存在的 chunk。\n"
        )

    return (
        _SYSTEM_PROMPT_BASE
        + client_context
        + risk_framing
        + section6_block
        + preference_block
        + cross_check_block  # v1.x A5a
        + debate_block  # v1.x A5b
        + f"\n\n# Insights\n{insights_str}\n"
        + f"\n# 用户原始需求 / 标的信息\n{state.user_message}\n"
        + f"\n# 本次 request_id(填入 JSON 的 request_id 字段)\n{state.request_id}\n"
        + f"\n# 投资研究员 SOP (跨 11 维度方法论)\n\n{_SOP_TEXT}\n"
        + feedback_block
        + "\n请严格按上方 JSON 模板输出,不要更改任何字段名。"
    )


# ---------------------------------------------------------------------------
# 去推荐改造后的 post-processing —— 不再覆盖评级/仓位;仅保留 A5a 估值 cross-check
# 覆盖 + A5b 多空辩论注入 § 6 综合研判。
# ---------------------------------------------------------------------------


def post_process_writer_output(
    state: ResearchState, llm_report: InvestmentDueDiligenceReport
) -> InvestmentDueDiligenceReport:
    """去推荐后 § 6 的确定性后处理。

    - 不再用 Python 覆盖评级 / 仓位(推荐引擎已下线)。
    - A5a:若 Analyst 算出 multi-model cross-check 结果,以 state 覆盖 LLM 占位
      (Calculator+Router+OutlierDiagnosis 是 single source of truth)。
    - A5b:若跑了 bull/bear debate,把 final 论据注入 § 6 InvestmentSynthesis。

    纯函数 — 对固定 (state, llm_report) 幂等。
    """
    report_updates: dict[str, Any] = {}

    # v1.x A5a: 若 Analyst 算出了 multi-model cross-check 结果,覆盖 LLM 占位。
    # Calculator+Router+OutlierDiagnosis 是 single source of truth,
    # LLM 在 financial_analysis.valuation_analysis 写的数字一律以 state 为准。
    if state.valuation_analysis is not None:
        new_financial = llm_report.financial_analysis.model_copy(
            update={"valuation_analysis": state.valuation_analysis}
        )
        report_updates["financial_analysis"] = new_financial

    # v1.x A5b: 若 Analyst 跑了 bull/bear debate,拷 final 论据进 InvestmentSynthesis。
    # rounds_completed=2 用 v2 (debate 完整收敛),rounds_completed=1 fallback 用 v1。
    if state.debate_trace is not None:
        if state.debate_trace.rounds_completed == 2:
            bull_final = state.debate_trace.bull_v2
            bear_final = state.debate_trace.bear_v2
        else:
            bull_final = state.debate_trace.bull_v1
            bear_final = state.debate_trace.bear_v1

        debate_updates: dict[str, Any] = {}
        if bull_final is not None:
            debate_updates["bull_case"] = list(bull_final.arguments)
            debate_updates["strongest_bull_point"] = bull_final.strongest_argument
        if bear_final is not None:
            debate_updates["bear_case"] = list(bear_final.arguments)
            debate_updates["strongest_bear_point"] = bear_final.strongest_argument

        if debate_updates:
            new_synthesis = llm_report.investment_synthesis.model_copy(update=debate_updates)
            report_updates["investment_synthesis"] = new_synthesis

    if not report_updates:
        return llm_report
    return llm_report.model_copy(update=report_updates)


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
        # 去推荐后:post-process 仅做 A5a 估值覆盖 + A5b 多空辩论注入 § 6 综合研判。
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
        """Async wrapper around the sync step() for full_research mode.

        v0.9.x fix: ``asyncio.to_thread`` so the blocking sync LLMService.chat
        does not stall the FastAPI event loop driving SSE streaming.
        """
        sr = await asyncio.to_thread(self.step, state)
        return state.model_copy(update=sr.state_update)

    async def _run_alert_writer(self, state: ResearchState) -> ResearchState:
        """Output PortfolioWarningReport (alert_deep_dive mode).

        v0.9.x fix: ``asyncio.to_thread`` around the sync LLM call so the
        FastAPI event loop is never blocked.
        """
        prompt = _build_alert_prompt(state)
        response = await asyncio.to_thread(
            self._llm.chat,
            prompt=prompt,
            tier="fast",  # alert deep_dive 短任务,走 fast
            schema=PortfolioWarningReport,
            request_id=state.request_id,
        )
        if response.parsed is None:
            # Defensive fallback — Writer 走 schema 模式未解析时直接抛
            raise RuntimeError("alert writer LLM returned no parsed PortfolioWarningReport")
        return state.model_copy(update={"portfolio_warning_report": response.parsed})
