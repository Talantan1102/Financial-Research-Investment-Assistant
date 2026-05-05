"""ResearchPlanner — decomposes research intent into subtasks conditioned on 6 input fields.

v0.8.4: 4 plan templates routed by investment_objective; prompt explicitly
        references investment_horizon + risk_tolerance so DataCollector and
        downstream agents are guided by client context.

spec ref: docs/superpowers/specs/2026-05-04-v0.8.4-b1-single-deep-design.md § 5.3
"""

from __future__ import annotations

import json
import re

from app.agents.base import Agent
from app.agents.schemas import (
    InvestmentObjective,
    ResearchPlan,
    ResearchState,
    StepResult,
)
from app.services.llm_response import Tier

# ---------------------------------------------------------------------------
# Shared schema block (appended to every template)
# ---------------------------------------------------------------------------

_SCHEMA_BLOCK = """
输出格式:仅输出 JSON,符合以下 schema:
{
  "subtasks": [
    {"subtask_id": "...", "description": "...", "required_tools": ["..."], "rationale": "..."}
  ],
  "target_entity": "<股票代码或公司名>",
  "research_style": "comprehensive",
  "reasoning": "<1-2 句拆分思路>"
}

可用数据点(后续 DataCollector 会调对应工具):
- 行情数据(get_stock_quote)
- 财务数据(get_financials)
- 财经新闻(get_news)
- 网络搜索(web_search)
- 知识库搜索(kb_search)
"""

# ---------------------------------------------------------------------------
# Template: capital_preservation (保本 / 保值)
# 偏重: 风险数据 / 财务健康度 / 偿债能力 / 下行保护
# spec § 5.3 row 1
# ---------------------------------------------------------------------------

_PLAN_TEMPLATE_CAPITAL_PRESERVATION = """你是金融研究助手 research_planner。

客户画像: investment_objective=capital_preservation(保本保值), \
investment_horizon={investment_horizon}, risk_tolerance={risk_tolerance}

本次研究核心诉求: **为 capital_preservation 类型客户做 {investment_horizon} 期投资研究。\
客户首要目标是保本,其次才是增值。请重点关注以下维度:**

1. **风险评估**(最高优先级): 信用风险 / 流动性风险 / 市场波动风险 / 尾部风险
2. **财务健康度**: 资产负债率 / 流动比率 / 现金覆盖情况 / 偿债能力
3. **下行保护**: 历史最大回撤 / 波动率 / 止损位置 / 安全边际
4. **股息与现金流**: 股息率 / 股息稳定性 / 自由现金流 / 分红持续性

相对次要:成长性 / 估值溢价(保本客户对高成长不需要高溢价承受度)

子任务拆分建议(2-4 个):
- 子任务 1: 行情 + 风险指标(get_stock_quote + get_financials → 财务健康 / 杠杆)
- 子任务 2: 新闻 + 网络搜索(get_news + web_search → 信用事件 / 重大风险)
- 子任务 3: 知识库搜索(kb_search → 保本策略相关研报 / 风险分析)

{schema_block}
"""

# ---------------------------------------------------------------------------
# Template: stable_growth (稳健增长)
# 偏重: 基本面质量 / 股息稳定性 / 盈利可持续性 / 竞争地位
# spec § 5.3 row 2
# ---------------------------------------------------------------------------

_PLAN_TEMPLATE_STABLE_GROWTH = """你是金融研究助手 research_planner。

客户画像: investment_objective=stable_growth(稳健增长), \
investment_horizon={investment_horizon}, risk_tolerance={risk_tolerance}

本次研究核心诉求: **为 stable_growth 类型客户做 {investment_horizon} 期投资研究。\
客户希望在控制风险的前提下实现稳健增值。请重点关注以下维度:**

1. **基本面质量**(最高优先级): ROE / 毛利率 / 净利润增速 / 盈利质量(现金含量)
2. **股息与分红**: 股息率 / 分红政策稳定性 / 派息比率
3. **竞争护城河**: 市场地位 / 品牌壁垒 / 行业集中度 / 定价权
4. **风险底线**: 资产负债率 / 流动比率(达标即可,非优先)

相对次要:短期技术指标 / 投机性成长预期

子任务拆分建议(3-4 个):
- 子任务 1: 财务指标(get_financials → ROE / 毛利率 / 盈利增速)
- 子任务 2: 行情 + 估值(get_stock_quote → 股息率 / PE/PB 估值水平)
- 子任务 3: 行业与竞争(web_search + get_news → 行业地位 / 政策 / 竞争格局)
- 子任务 4: 知识库搜索(kb_search → 稳健增长相关研报 / 基本面分析)

{schema_block}
"""

# ---------------------------------------------------------------------------
# Template: balanced (均衡 / 平衡收益与风险)
# 偏重: 基本面 + 估值 + 风险均衡分析
# spec § 5.3 row 3
# ---------------------------------------------------------------------------

_PLAN_TEMPLATE_BALANCED = """你是金融研究助手 research_planner。

客户画像: investment_objective=balanced(均衡配置), \
investment_horizon={investment_horizon}, risk_tolerance={risk_tolerance}

本次研究核心诉求: **为 balanced 类型客户做 {investment_horizon} 期投资研究。\
客户期望在收益与风险之间取得均衡,兼顾基本面质量和合理估值。\
请覆盖以下维度并均衡权重:**

1. **财务基本面**: ROE / 盈利质量 / 成长性 / 现金流
2. **估值合理性**: PE/PB 历史百分位 / 与同行对比 / DCF 估值
3. **风险评估**: 整体风险等级 / 流动性 / 杠杆情况
4. **行业与市场环境**: 景气度 / 政策 / 竞争格局
5. **股息 / 持有体验**: 股息率 / 波动率

子任务拆分建议(3-4 个):
- 子任务 1: 财务数据(get_financials → 盈利 / 成长 / 资产负债)
- 子任务 2: 行情数据(get_stock_quote → 估值快照 / 市值)
- 子任务 3: 新闻 + 搜索(get_news + web_search → 行业 / 政策 / 近期事件)
- 子任务 4: 知识库搜索(kb_search → 综合研报)

{schema_block}
"""

# ---------------------------------------------------------------------------
# Template: aggressive_growth (激进成长)
# 偏重: 成长性 / 估值空间 / 行业赛道 / 催化剂
# spec § 5.3 row 4
# ---------------------------------------------------------------------------

_PLAN_TEMPLATE_AGGRESSIVE_GROWTH = """你是金融研究助手 research_planner。

客户画像: investment_objective=aggressive_growth(激进成长), \
investment_horizon={investment_horizon}, risk_tolerance={risk_tolerance}

本次研究核心诉求: **为 aggressive_growth 类型客户做 {investment_horizon} 期投资研究。\
客户愿意承受更高波动以追求高成长收益。请重点关注以下维度:**

1. **成长性**(最高优先级): 营收 / 净利润增速趋势 / 未来 3 年 CAGR 预测 / 新业务催化剂
2. **估值空间**: 当前 PE/PB 历史百分位 / 目标估值 / 是否存在估值重估机会
3. **行业赛道**: 赛道景气度 / 市场天花板 / 渗透率 / 政策催化
4. **竞争地位**: 市占率变化趋势 / 是否在扩大份额

相对次要:股息 / 偿债能力(成长型公司往往 capex 高、股息低,可接受)

子任务拆分建议(4-5 个):
- 子任务 1: 成长指标(get_financials → 营收 / 利润 / 成长率)
- 子任务 2: 行情 + 估值(get_stock_quote → 成长估值 / 市值空间)
- 子任务 3: 行业催化剂(web_search → 赛道机会 / 政策 / 竞争格局)
- 子任务 4: 新闻(get_news → 近期业绩 / 新产品 / 市场扩张信号)
- 子任务 5: 知识库搜索(kb_search → 成长型研报 / 估值模型)

{schema_block}
"""

# ---------------------------------------------------------------------------
# Template registry
# ---------------------------------------------------------------------------

_TEMPLATES: dict[str, str] = {
    "capital_preservation": _PLAN_TEMPLATE_CAPITAL_PRESERVATION,
    "stable_growth": _PLAN_TEMPLATE_STABLE_GROWTH,
    "balanced": _PLAN_TEMPLATE_BALANCED,
    "aggressive_growth": _PLAN_TEMPLATE_AGGRESSIVE_GROWTH,
}


def build_planner_prompt(state: ResearchState) -> str:
    """Build planner system prompt conditioned on state.investment_objective.

    Routes to one of 4 plan templates based on investment_objective.
    Falls back to balanced template if objective is None.
    """
    objective: InvestmentObjective = state.investment_objective or "balanced"
    template = _TEMPLATES.get(objective, _PLAN_TEMPLATE_BALANCED)

    system = template.format(
        investment_horizon=state.investment_horizon or "medium_term",
        risk_tolerance=state.risk_tolerance or "moderate",
        schema_block=_SCHEMA_BLOCK,
    )

    # Append context block with target + user message
    ts_code = state.target_ts_code or ""
    target_line = f"# 目标标的\n{ts_code}\n" if ts_code else ""
    user_line = f"# 用户研报需求\n{state.user_message}\n"

    return system + f"\n{target_line}{user_line}\n请输出 JSON。"


def _parse_plan(content: str) -> ResearchPlan:
    """Strip code fences, json.loads, ResearchPlan validate."""
    cleaned = re.sub(r"^```(?:json)?\s*", "", content.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```\s*$", "", cleaned)
    data = json.loads(cleaned)
    return ResearchPlan.model_validate(data)


class ResearchPlanner(Agent):
    name = "ResearchPlanner"
    model_tier: Tier = "balanced"

    def step(self, state: ResearchState) -> StepResult:  # type: ignore[override]
        """Build a planner prompt conditioned on 6 input fields, call LLM, parse plan JSON."""
        prompt = build_planner_prompt(state)
        r = self._llm.chat(prompt=prompt, tier=self.model_tier, request_id=state.request_id)
        plan = _parse_plan(r.content)
        return StepResult(
            state_update={"plan": plan},
            span_metadata={"agent": "ResearchPlanner", "model": r.model, "cost_cny": r.cost_cny},
        )
