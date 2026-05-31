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

v0.8.5 Task 9 forward concerns wired into prompt + post-process:
  1. valuation_analysis.pe_historical_percentile_value (numeric 0-1 sibling)
  2. financial_analysis.debt_ratio_assessment (Literal[健康/一般/警戒/高风险])
  3. post_process_writer_output appends deterministic narrative footer that
     announces Python override of recommendation + position pct.

spec ref: docs/superpowers/specs/2026-05-04-v0.8.4-b1-single-deep-design.md § 3 / § 5.3
spec ref: docs/superpowers/specs/2026-05-04-v0.8.5-constrained-router-design.md § Task 5
spec ref: docs/superpowers/plans/2026-05-05-v0.8.5-constrained-router-implementation.md § Task 9
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Any

from app.agents.base import Agent
from app.agents.investment_dd_renderer import render_investment_dd_report_markdown
from app.agents.investment_dd_schema import InvestmentDueDiligenceReport
from app.agents.portfolio_warning_schema import PortfolioWarningReport
from app.agents.schemas import Recommendation, ResearchState, StepResult
from app.services.llm_response import Tier
from app.skills.financial_research import _SOP_TEXT  # C62: single SSOT for SOP text
from app.skills.financial_research.scripts import (
    classify_recommendation,
    compute_position_size_pct,
)

# v0.8.5 — narrative footer sentinel for idempotent post_process. Use HTML
# comment so markdown rendering hides it; LLM quoting the visible text
# "Python 决定论修正" cannot accidentally trip the idempotent skip check.
_FOOTER_SENTINEL = "<!-- v0.8.5-pyoverride-v1 -->"


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


def _format_user_preferences(state: ResearchState) -> str:
    """Return a formatted preference block for the prompt, or empty string.

    v0.9 — when chat_extracted_preferences is non-empty, injects a section
    that instructs the LLM to honor user-expressed preferences (horizon,
    risk_tolerance, etc.) in the investment_recommendation narrative.
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
        f"**§ 6 投资建议 narrative 要求**:必须显式列举 **≥ 2 条 bull arguments + ≥ 2 条 bear arguments**;\n"
        f"必须基于 strongest_bull + strongest_bear 综合给最终推荐。**禁止只挑一面之词**\n"
        f"(打架 = signal, narrative 必须诚实双向论证)。\n"
    )


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
# v0.8.5 post-processing — deterministic override of LLM-generated
# recommendation + position size. Skill bundle scripts are the single source
# of truth for these two fields.
# ---------------------------------------------------------------------------


# v0.8.5 forward concern 1 — regex fallback for pe_historical_percentile str.
# Captures the first numeric (int or decimal) followed by 0+ whitespace and
# "分位" (e.g. "近 5 年 30 分位" → "30", "30.5 分位" → "30.5"). Returns the
# normalised float in [0.0, 1.0] or None on no match.
_PE_PERCENTILE_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*分位")


def _parse_pe_percentile_str(s: str | None) -> float | None:
    """Best-effort regex parse of '近 5 年 30 分位' → 0.30.

    Returns None when no '<num> 分位' substring is found, allowing the caller
    to apply its own default (typically 0.5 for missing data). Defensive
    against LLM outputs that mix half-numerals or missing 分位 token.
    """
    if not s:
        return None
    m = _PE_PERCENTILE_PATTERN.search(s)
    if m is None:
        return None
    try:
        raw = float(m.group(1))
    except ValueError:
        return None
    # Treat values >1 as percentage (e.g. "30 分位" → 30 → 0.30); values ≤1
    # already normalized (e.g. "0.3 分位" → 0.3).
    pct = raw / 100.0 if raw > 1.0 else raw
    if 0.0 <= pct <= 1.0:
        return pct
    return None


def _extract_metrics_from_llm_report(report: dict[str, Any]) -> dict[str, Any]:
    """Extract metrics dict consumed by classify_recommendation.

    Resolution order for ``pe_percentile``:
      1. ``valuation_analysis.pe_historical_percentile_value`` (v0.8.5 numeric)
      2. regex parse of ``valuation_analysis.pe_historical_percentile`` str
         (e.g. "近 5 年 30 分位" → 0.30)
      3. 0.5 (中位) — missing/unparseable, neither buy nor sell red-line.

    Other fields the schema does not guarantee (``roe``, ``revenue_yoy``, etc.)
    fall through to defaults causing classify_recommendation to drop to its
    ``recommend_hold`` fallback rule. The deterministic override is what
    matters: the LLM cannot talk the recommendation up via narrative alone.
    """
    fa: dict[str, Any] = report.get("financial_analysis") or {}
    va: dict[str, Any] = fa.get("valuation_analysis") or {}
    overview: dict[str, Any] = report.get("target_overview") or {}

    # v0.8.5 forward concern 1 — numeric > regex > 0.5 fallback chain.
    # bool subclass guard: Python bool is int subclass (isinstance(True, int) == True),
    # so without this guard pe_historical_percentile_value=True (LLM bug) would pass
    # the 0.0 <= 1.0 <= 1.0 range check and silently misroute to sell red-line.
    pe_pct: float
    pe_numeric = va.get("pe_historical_percentile_value")
    if (
        isinstance(pe_numeric, int | float)
        and not isinstance(pe_numeric, bool)
        and 0.0 <= float(pe_numeric) <= 1.0
    ):
        pe_pct = float(pe_numeric)
    else:
        parsed = _parse_pe_percentile_str(va.get("pe_historical_percentile"))
        pe_pct = parsed if parsed is not None else 0.5

    return {
        "pe_percentile": pe_pct,
        "roe": fa.get("roe") or 0.0,
        "revenue_yoy": fa.get("revenue_yoy") or 0.0,
        "net_profit_yoy": fa.get("net_profit_yoy") or 0.0,
        # 1 万亿 CNY large-cap 中位 default — 避免 missing data 误触发 small-cap haircut
        # (`or` 对 0.0 也 fallback, 但真"market_cap=0"极罕见; 跟 writer.py:114 prompt-side
        # default 1e12 anchor 一致).
        "market_cap_cny": overview.get("current_market_cap") or 1_000_000_000_000.0,
        "forecast_signal": fa.get("forecast_signal") or "neutral",
        # v0.8.5 forward concern 3 — debt_ratio_assessment now schema-real.
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
      - narrative footer appended announcing the override (forward concern 2).
        This guarantees the LLM-narrative number cannot drift from the final
        Python-decided number. v0.9 will replace this with a 2nd LLM rewrite
        for fluency; v0.8.5 keeps it deterministic and idempotent.

    All other fields (prices, holding_period, evidence) remain LLM-authored.
    Pure function — idempotent on a fixed (state, llm_report) pair.
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

    # v0.8.5 forward concern 2 — narrative footer announcing Python override.
    # Idempotency guard uses HTML comment sentinel _FOOTER_SENTINEL (markdown-
    # invisible) so an LLM-narrative that quotes the visible "Python 决定论修正"
    # phrase cannot accidentally trip the skip check.
    base_narrative = (llm_report.investment_recommendation.narrative or "").rstrip()
    if _FOOTER_SENTINEL not in base_narrative:
        narrative_with_footer = (
            f"{base_narrative}\n\n"
            f"---\n"
            f"{_FOOTER_SENTINEL}\n"
            f"📊 Python 决定论修正: 评级 = {classified_rec}, 仓位 = {pct:.2f}%"
            f" (基于客户 risk_tolerance={risk_tolerance} + 市值数据 + skill bundle 规则)。"
        ).strip()
    else:
        narrative_with_footer = base_narrative

    new_recommendation = llm_report.investment_recommendation.model_copy(
        update={
            "recommendation": classified_rec,
            "recommended_position_size_pct": pct,
            "narrative": narrative_with_footer,
        }
    )
    report_updates: dict[str, Any] = {"investment_recommendation": new_recommendation}

    # v1.x A5a: 若 Analyst 算出了 multi-model cross-check 结果,覆盖 LLM 占位。
    # Python 决定论 — Calculator+Router+OutlierDiagnosis 是 single source of truth,
    # LLM 在 financial_analysis.valuation_analysis 写的数字一律以 state 为准。
    if state.valuation_analysis is not None:
        new_financial = llm_report.financial_analysis.model_copy(
            update={"valuation_analysis": state.valuation_analysis}
        )
        report_updates["financial_analysis"] = new_financial

    # v1.x A5b: 若 Analyst 跑了 bull/bear debate,拷 final 论据进 InvestmentRecommendation。
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
            new_recommendation = new_recommendation.model_copy(update=debate_updates)
            report_updates["investment_recommendation"] = new_recommendation

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
