"""Critic 第 6 scorer — input_context_appropriateness.

评判报告内容是否真正针对 6 个结构化输入字段(investment_objective /
investment_horizon / risk_tolerance / client_total_aum / target_ts_code /
client_existing_position)进行了差异化定制,而非输出 generic boilerplate。

判断标准:
  - differential(得分高): 报告显式引用投资目标/期限/风险偏好,仓位建议与
    客户 AUM 和风险等级匹配,关键词体现 client-specific 定制
  - generic boilerplate(得分低): 报告内容与任何客户通用,不提及 input 字段
    的具体值,或 § 6 仓位建议与客户特征明显不符

scale: 0–10(与其他 5 个维度一致);acceptance threshold = 8.5(≡ 0.85 normalized)
"""

from __future__ import annotations

import json
import re

from app.agents.base import Agent
from app.agents.schemas import (
    CriticDimensionScore,
    ResearchState,
    StepResult,
)
from app.services.llm_response import Tier

_INPUT_CONTEXT_PROMPT = """你是金融研究助手 critic_input_context_scorer。

任务:评判以下投资尽调报告是否真正基于客户 6 个结构化输入字段进行了差异化定制。
评分区间:0-10 分(0=完全 generic boilerplate,10=每个字段都驱动了具体内容)。

# 客户输入字段(Ground Truth)
- investment_objective (投资目标): {investment_objective}
- investment_horizon (投资期限): {investment_horizon}
- risk_tolerance (风险承受度): {risk_tolerance}
- client_total_aum (客户 AUM, CNY): {client_total_aum}
- target_ts_code (标的代码): {target_ts_code}
- client_existing_position (现有持仓, CNY): {client_existing_position}

# 评分标准 — 什么算"真正 differential"(高分)

## 核心维度 1: § 6 仓位与持有期
- recommended_position_size_pct 与 risk_tolerance 匹配
  (conservative → ≤10%; moderate/balanced → 5%-20%; aggressive/very_aggressive → >10%)
- recommended_holding_period 与 investment_horizon 一致
  (short_term → short_term; medium_term → medium_term; long_term → long_term)

## 核心维度 2: 投资目标关键词
- 报告明确提及 investment_objective 对应的核心目标关键词
  (capital_preservation → 保本/稳健/防御/安全边际;
   stable_growth → 稳健增长/价值;
   balanced → 均衡/价值与成长;
   aggressive_growth → 成长/高弹性/进攻/成长性催化剂)

## 核心维度 3: 风险叙事倾向(注意:overall_risk_level 是标的客观风险,不受客户风险偏好影响)
- § 5 风险评估的 narrative 叙述角度与客户 risk_tolerance 对齐:
  保守客户 → narrative 强调下行保护、止损机制、安全边际;
  激进客户 → narrative 强调上行潜力、催化剂、可接受波动范围;
  均衡客户 → narrative 均衡呈现上下行;
- 注意:overall_risk_level 字段(low/medium/high)是对标的客观风险的评级,
  与客户风险偏好无关,不应作为 differential 的判断依据。

## 核心维度 4: § 6 投资建议 narrative
- narrative 明确引用客户的投资目标和风险承受度进行解释
  (如"基于您 aggressive_growth + very_aggressive 的特征..." 或类似表述)

# 评分标准 — 什么算"generic boilerplate"(低分)
- § 6 仓位建议不论 risk_tolerance 都推荐相同百分比
- 报告没有提及 investment_objective 对应的关键词,或关键词与目标明显不符
  (如 capital_preservation 客户的报告全文强调高成长/高弹性)
- § 6 持有期建议与 investment_horizon 相反或无关
- § 5 narrative 对所有客户叙述方式相同,未针对风险偏好调整叙述角度
- § 6 投资建议 narrative 中完全不提 investment_objective 或 risk_tolerance

# 报告关键章节(§ 5 风险评估 + § 6 投资建议 + 报告开头摘要)
# 注:只提供关键章节用于评分,以节约 token
{report_excerpt}

输出 JSON(只输出 JSON,不加任何解释):
{{"score": <0-10 的整数或一位小数>, "evidence": "<2-3 句话:1句指出最强的 differential 证据(仓位/持有期/关键词/narrative),1句指出最弱的 differential 或 boilerplate 迹象>"}}
"""


class InputContextAppropriatenessScorer(Agent):
    """Critic 第 6 scorer — 评判报告是否真正 condition on 6 input 字段。

    不继承 _BaseScorer(其 prompt 只含 report_markdown + context,无 6 字段),
    自定义 step() 把 ResearchState 的 6 个结构化字段注入 judge prompt。
    """

    name = "InputContextAppropriatenessScorer"
    dimension = "input_context_appropriateness"
    state_field = "input_context_appropriateness_score"
    model_tier: Tier = "fast"

    def step(self, state: ResearchState) -> StepResult:  # type: ignore[override]
        prompt = _INPUT_CONTEXT_PROMPT.format(
            investment_objective=state.investment_objective or "(未指定)",
            investment_horizon=state.investment_horizon or "(未指定)",
            risk_tolerance=state.risk_tolerance or "(未指定)",
            client_total_aum=(
                f"{state.client_total_aum:,.0f}"
                if state.client_total_aum is not None
                else "(未指定)"
            ),
            target_ts_code=state.target_ts_code or "(未指定)",
            client_existing_position=(
                f"{state.client_existing_position:,.0f}"
                if state.client_existing_position is not None
                else "无"
            ),
            # Pass only the report excerpt (§5 + §6 + header) to avoid token overflow.
            # The judge prompt only needs to evaluate:
            #   1. position_size_pct and holding_period (§ 6)
            #   2. investment_objective keywords (§ 6 narrative)
            #   3. risk framing (§ 5 narrative)
            # Truncating to 3000 chars covers §5 and §6 in full.
            report_excerpt=_extract_report_excerpt(state.report_markdown or "(empty)"),
        )
        r = self._llm.chat(prompt=prompt, tier=self.model_tier, request_id=state.request_id)
        score = _parse_input_context_score(r.content, request_id=r.request_id or state.request_id)
        return StepResult(
            state_update={self.state_field: score},
            span_metadata={
                "agent": self.name,
                "dimension": self.dimension,
                "model": r.model,
                "cost_cny": r.cost_cny,
            },
        )


def _extract_report_excerpt(report_markdown: str) -> str:
    """Extract the most relevant sections for input_context scoring.

    Keeps § 5 (risk assessment) and § 6 (investment recommendation) in full,
    plus the first 400 chars of the report header/overview for context.
    Limits total excerpt to ~3000 chars to prevent token overflow in judge call.

    The judge needs §5 (risk narrative framing) and §6 (position_size, holding_period,
    recommendation narrative) — these are the sections most sensitive to the 6 input fields.
    """
    if not report_markdown or report_markdown == "(empty)":
        return "(empty)"

    header = report_markdown[:400]

    # Extract § 5 and § 6 sections
    sec5_start = report_markdown.find("## § 5")
    sec6_start = report_markdown.find("## § 6")

    sec5 = ""
    if sec5_start != -1:
        # § 5 ends where § 6 begins
        sec5_end = sec6_start if sec6_start != -1 else len(report_markdown)
        sec5 = report_markdown[sec5_start:sec5_end][:800]  # cap at 800 chars

    sec6 = ""
    if sec6_start != -1:
        # § 6 ends at footnotes or end of file
        sec6_end = report_markdown.find("---\n", sec6_start)
        if sec6_end == -1:
            sec6_end = len(report_markdown)
        sec6 = report_markdown[sec6_start:sec6_end][:1200]  # cap at 1200 chars

    parts = [header]
    if sec5:
        parts.append("\n...\n")
        parts.append(sec5)
    if sec6:
        parts.append("\n...\n")
        parts.append(sec6)

    excerpt = "\n".join(parts)
    return excerpt[:3000]  # hard cap at 3000 chars


def _parse_input_context_score(content: str, *, request_id: str) -> CriticDimensionScore:
    cleaned = re.sub(r"^```(?:json)?\s*", "", content.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```\s*$", "", cleaned)
    data = json.loads(cleaned)
    return CriticDimensionScore(
        dimension="input_context_appropriateness",
        score=float(data["score"]),
        evidence=str(data.get("evidence", "")),
        sub_agent_request_id=request_id,
    )


__all__ = ["InputContextAppropriatenessScorer"]
