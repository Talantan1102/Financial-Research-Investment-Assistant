"""Analyst — synthesizes tool_results into structured Insights.

v0.8.4: prompt is conditioned on investment_horizon + investment_objective from
        ResearchState so the analyst weights dimensions appropriate to the client context.
v0.8.5: prompt appended with composed_sop() from financial_research skill bundle
        (11 methodology dimensions injected as a single SOP block).

spec ref: docs/superpowers/specs/2026-05-04-v0.8.4-b1-single-deep-design.md § 5.3
spec ref: docs/superpowers/specs/2026-05-04-v0.8.5-constrained-router-design.md § Task 5
"""

from __future__ import annotations

import json
import re

from app.agents.base import Agent
from app.agents.schemas import Insight, ResearchState, StepResult
from app.services.llm_response import Tier
from app.skills.financial_research import load_skill

# Module-level skill load — methodology + references parsed once at import time.
_SKILL_BUNDLE = load_skill()
_SOP_TEXT = _SKILL_BUNDLE.composed_sop()

_BASE_SYSTEM_PROMPT = """你是金融研究助手 analyst。

任务:基于 ResearchPlan 的子任务和 DataCollector 收集到的工具结果,产出 list[Insight]。
每个 Insight 关联一个 subtask_id,提炼 1-2 句关键发现 + 引用支持数据。

输出 JSON:
{{
  "insights": [
    {{
      "subtask_id": "...",
      "finding": "...",
      "supporting_data": [{{"key": "price", "value": "1820.5"}}],
      "confidence": "high|medium|low"
    }}
  ]
}}

注意:supporting_data 每个元素必须是 JSON 对象(dict),不能是字符串。
"""

# ---------------------------------------------------------------------------
# Horizon-specific instruction blocks
# spec § 5.3: 短期看技术+资金流; 中期均衡; 长期看基本面+行业地位
# ---------------------------------------------------------------------------

_HORIZON_INSTRUCTIONS: dict[str, str] = {
    "short_term": """
## 投资期限维度指令: short_term(短期 < 6 个月)

本次为**短期**投资分析,请在 insights 中优先关注:
1. **技术面信号**: 近期价格趋势 / 支撑阻力位 / 量价关系
2. **资金流向**: 北向资金 / 主力资金净流入 / 融资余额变化
3. **近期催化剂**: 业绩预告 / 重大公告 / 政策事件
4. **短期风险**: 高波动 / 流动性风险 / 消息面不确定性

长期基本面数据仍需引用(形成背景认知),但权重低于技术面。
""",
    "medium_term": """
## 投资期限维度指令: medium_term(中期 6-24 个月)

本次为**中期**投资分析,请在 insights 中均衡关注:
1. **基本面质量**: 盈利能力(ROE / 毛利率)/ 成长性(营收 / 净利润增速)
2. **估值合理性**: PE/PB 历史百分位 / 与同行估值对比
3. **行业趋势**: 景气度 / 竞争格局变化
4. **风险底线**: 资产负债率 / 流动比率 / 重大风险信号

技术面数据可作为辅助参考,不是主要权重。
""",
    "long_term": """
## 投资期限维度指令: long_term(长期 > 24 个月)

本次为**长期**投资分析,请在 insights 中重点关注:
1. **基本面长期可持续性**: 护城河 / 行业地位 / ROE 趋势
2. **成长赛道**: 行业天花板 / 市场份额变化 / 长期 CAGR
3. **资本配置质量**: 自由现金流 / 资本回报率 / 股东回报(股息 + 回购)
4. **长期风险**: 行业颠覆风险 / 竞争格局劣化 / 监管政策变化

短期技术指标权重最低;关注 3-5 年维度的竞争壁垒与成长空间。
""",
}

# ---------------------------------------------------------------------------
# Objective-specific weighted instruction blocks
# ---------------------------------------------------------------------------

_OBJECTIVE_INSTRUCTIONS: dict[str, str] = {
    "capital_preservation": """
## 投资目标加权指令: capital_preservation(保本保值)

**加权维度**: 风险识别 + 下行保护 + 财务健康
- 重点提炼: 债务偿还能力 / 流动性覆盖 / 历史最大回撤 / 信用风险信号
- 对任何重大风险信号给予 high confidence 的 insight,不要淡化
- 估值 insight: 强调安全边际是否充足,是否有下行空间
""",
    "stable_growth": """
## 投资目标加权指令: stable_growth(稳健增长)

**加权维度**: 盈利质量 + 股息稳定性 + 护城河
- 重点提炼: ROE 趋势 / 股息率 / 派息比率 / 盈利现金含量
- 竞争地位 insight: 强调品牌壁垒 / 市场份额 / 定价权
- 不需要激进成长预测
""",
    "balanced": """
## 投资目标加权指令: balanced(均衡配置)

**均衡维度**: 盈利 + 估值 + 风险 + 行业各占一定权重
- 覆盖面优先于深度:每个主要维度都要有 insight
- 避免只关注某一方面(不能全是风险,也不能全是成长)
""",
    "aggressive_growth": """
## 投资目标加权指令: aggressive_growth(激进成长)

**加权维度**: 成长性 + 估值重估空间 + 催化剂
- 重点提炼: 营收 / 净利润增速趋势 / 未来成长驱动因素
- 估值 insight: 当前估值是否已反映成长,是否存在 re-rating 机会
- 风险维度不需要过度展开(客户已知道承受高波动)
""",
}


def _format_chat_signals(state: ResearchState) -> str:
    """Format chat-derived entities + preferences for analyst prompt (E13).

    Injected only when ResearchState carries chat_extracted_entities with
    comparative_target role or non-empty chat_extracted_preferences.
    Returns an empty string when no signals are present (no block injected).
    """
    parts = []
    comparative = [e for e in state.chat_extracted_entities if e.role == "comparative_target"]
    if comparative:
        names = ", ".join(f"{e.name} ({e.ts_code})" if e.ts_code else e.name for e in comparative)
        parts.append(
            f"\n【用户在 chat 中比较过的对标公司 (comparative_target)】: {names}\n"
            f"→ 在 industry_analysis 中包含这些公司的对比分析。"
        )
    if state.chat_extracted_preferences:
        prefs = "; ".join(f"[{p.category}] {p.text}" for p in state.chat_extracted_preferences)
        parts.append(f"\n【用户偏好】: {prefs}\n→ 分析角度需贴合这些偏好。")
    return "\n".join(parts) if parts else ""


def build_analyst_prompt(state: ResearchState) -> str:
    """Build analyst prompt conditioned on investment_horizon + investment_objective."""
    # horizon-specific instruction
    horizon = state.investment_horizon or "medium_term"
    horizon_block = _HORIZON_INSTRUCTIONS.get(horizon, _HORIZON_INSTRUCTIONS["medium_term"])

    # objective-specific weighted instruction
    objective = state.investment_objective or "balanced"
    objective_block = _OBJECTIVE_INSTRUCTIONS.get(objective, _OBJECTIVE_INSTRUCTIONS["balanced"])

    # Client context line (injected in system prompt)
    context_line = (
        f"\n## 客户背景\n"
        f"investment_objective={objective}, "
        f"investment_horizon={horizon}, "
        f"risk_tolerance={state.risk_tolerance or 'moderate'}\n"
    )

    system = _BASE_SYSTEM_PROMPT + context_line + horizon_block + objective_block

    # Subtask plan summary
    plan_summary = ""
    if state.plan is not None:
        for sub in state.plan.subtasks:
            plan_summary += f"- [{sub.subtask_id}] {sub.description}\n"

    tool_summary = "\n".join(
        f"- {tr.tool_name}({tr.args}) → success={tr.success} output={tr.output}"
        for tr in state.tool_results
    )

    # Chat-derived signals block (E13) — empty string when no signals present
    chat_signals_block = _format_chat_signals(state)

    return (
        system
        + f"\n\n# Subtasks\n{plan_summary}\n# Tool Results\n{tool_summary}\n"
        + f"\n# 投资研究员 SOP (跨 11 维度方法论)\n\n{_SOP_TEXT}\n"
        + (f"\n# Chat 信号 (来自历史对话)\n{chat_signals_block}\n" if chat_signals_block else "")
        + "\n请输出 JSON。"
    )


def _parse_insights(content: str) -> list[Insight]:
    cleaned = re.sub(r"^```(?:json)?\s*", "", content.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```\s*$", "", cleaned)
    data = json.loads(cleaned)
    insights_raw = data["insights"]
    # Coerce subtask_id to str: LLM occasionally returns integer subtask_ids (e.g. 1 → "1")
    for item in insights_raw:
        if "subtask_id" in item and not isinstance(item["subtask_id"], str):
            item["subtask_id"] = str(item["subtask_id"])
    return [Insight.model_validate(i) for i in insights_raw]


class Analyst(Agent):
    name = "Analyst"
    model_tier: Tier = "balanced"

    def step(self, state: ResearchState) -> StepResult:  # type: ignore[override]
        prompt = build_analyst_prompt(state)
        r = self._llm.chat(prompt=prompt, tier=self.model_tier, request_id=state.request_id)
        insights = _parse_insights(r.content)
        return StepResult(
            state_update={"insights": insights},
            span_metadata={"agent": "Analyst", "model": r.model, "cost_cny": r.cost_cny},
        )
