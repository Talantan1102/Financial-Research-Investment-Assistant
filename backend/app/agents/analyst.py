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
import logging
import math
import re
from typing import Any

from app.agents.base import Agent
from app.agents.bear_advocate import BearAdvocate
from app.agents.bull_advocate import BullAdvocate
from app.agents.debate_orchestrator import DebateOrchestrator
from app.agents.debate_schemas import DebateTrace
from app.agents.investment_dd_schema import (
    OutlierDiagnosis,
    ValuationAnalysis,
    ValuationModel,
)
from app.agents.outlier_diagnosis_agent import OutlierDiagnosisAgent
from app.agents.schemas import Insight, ResearchState, StepResult, ToolResult
from app.agents.valuation_calculator import ValuationInputs, calculate_valuations
from app.agents.valuation_helpers.industry_defaults import (
    get_industry_dcf_defaults,
    normalize_industry,
)
from app.services.llm_response import Tier
from app.skills.financial_research import load_skill

logger = logging.getLogger(__name__)

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

        # v1.x A5a: try to compute multi-model valuation cross-check.
        # Graceful skip when state.tool_results 缺数据 — 不破既有 e2e。
        valuation_analysis = self._maybe_compute_valuation_analysis(state)

        # v1.x A5b: try to run bull/bear debate.
        # Graceful skip when 任何 advocate / orchestrator 失败 — 不破既有 e2e。
        debate_trace = self._maybe_run_debate(state)

        state_update: dict[str, Any] = {"insights": insights}
        if valuation_analysis is not None:
            state_update["valuation_analysis"] = valuation_analysis
        if debate_trace is not None:
            state_update["debate_trace"] = debate_trace

        return StepResult(
            state_update=state_update,
            span_metadata={"agent": "Analyst", "model": r.model, "cost_cny": r.cost_cny},
        )

    def _maybe_run_debate(self, state: ResearchState) -> DebateTrace | None:
        """v1.x A5b: 跑 bull/bear 2 轮 debate, 任何失败 graceful → None."""
        try:
            bull = BullAdvocate(llm=self._llm)
            bear = BearAdvocate(llm=self._llm)
            orchestrator = DebateOrchestrator(bull=bull, bear=bear)
            return orchestrator.run(state)
        except Exception as e:  # noqa: BLE001
            logger.warning("v1.x A5b: DebateOrchestrator 失败 (silent): %s", e)
            return None

    def _maybe_compute_valuation_analysis(self, state: ResearchState) -> ValuationAnalysis | None:
        """v1.x A5a hook. 从 state.tool_results 拼 inputs → ValuationAnalysis。

        设计:
        - 任何数据缺失都 graceful skip (return None),保证不破现有 e2e
        - severe consistency → 触发 OutlierDiagnosisAgent (亦 silent fail)
        - 本期 v1.x A5a Task 15 简化:_build_valuation_inputs_from_state 直接 return None;
          真 tushare wire 留下一 iteration。这样 hook 接通但占位不破任何 test。
        """
        try:
            inputs = self._build_valuation_inputs_from_state(state)
        except (KeyError, ValueError, AttributeError) as e:
            logger.debug("v1.x A5a: valuation_analysis skip (tool_results 缺数据): %s", e)
            return None
        if inputs is None:
            return None

        result = calculate_valuations(inputs, router_override=None)

        diagnosis: OutlierDiagnosis | None = None
        if result.valuation_consistency == "severe":
            diagnosis = self._maybe_diagnose_outlier(state, inputs, result)

        return ValuationAnalysis(
            narrative="v1.x A5a multi-model cross-check (Writer 阶段会扩充 narrative)",
            industry_classification=inputs.industry_classification,
            active_models=result.active_models,
            router_override_reasoning=result.router_override_reasoning,
            pe_value=result.pe_value,
            pb_value=result.pb_value,
            ev_ebitda_value=result.ev_ebitda_value,
            dcf_base=result.dcf_base,
            dcf_bull=result.dcf_bull,
            dcf_bear=result.dcf_bear,
            dcf_sensitivity=result.dcf_sensitivity,
            valuation_consistency=result.valuation_consistency,
            outlier_diagnosis=diagnosis,
        )

    def _maybe_diagnose_outlier(
        self,
        state: ResearchState,
        inputs: ValuationInputs,
        result: Any,
    ) -> OutlierDiagnosis | None:
        """severe consistency 时触发 OutlierDiagnosisAgent。silent fail on any error."""
        try:
            diagnosis_agent = OutlierDiagnosisAgent(llm=self._llm)

            vals: dict[str, float] = {}
            if result.pe_value is not None:
                vals["pe"] = result.pe_value
            if result.pb_value is not None:
                vals["pb"] = result.pb_value
            if result.ev_ebitda_value is not None:
                vals["ev_ebitda"] = result.ev_ebitda_value
            if result.dcf_base is not None:
                vals["dcf_base"] = result.dcf_base

            # 收 assumptions — 简化:仅 DCF (其它 model 假设少且不数值化)
            assumptions: dict[str, dict[str, float]] = {}
            if (
                ValuationModel.DCF in result.active_models
                and ValuationModel.DCF not in result.skipped_models
            ):
                assumptions["dcf"] = {
                    "industry_baseline_wacc": inputs.industry_baseline_wacc,
                    "industry_terminal_growth": inputs.industry_terminal_growth,
                }

            company_narrative = f"{state.target_ts_code or 'unknown'} - {state.user_message}"
            return diagnosis_agent.diagnose(
                valuations=vals,
                assumptions=assumptions,
                company_narrative=company_narrative,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("v1.x A5a: OutlierDiagnosisAgent 失败 (silent): %s", e)
            return None

    def _build_valuation_inputs_from_state(self, state: ResearchState) -> ValuationInputs | None:
        """从 state.tool_results 提取 valuation inputs;字段缺失 → None (graceful skip)。

        v1.x A5a follow-up #1 真实 wire — 现有 tool palette 数据现实约束:
        - 无 compare_industry_valuation tool (未注册) → industry PE 用个股历史 median_pe
          作为可比 fallback (narrative 阶段标注),industry PB 用 daily_basic.pb 单点 bracket
        - 无 stock_basic.industry tool → industry_classification 用 user_message 关键字
          substring match (白酒/银行/半导体等)推断,不命中走 _default
        - eps = price / pe / bvps = price / pb (从 daily_basic + stock_quote 反推,
          避免依赖未暴露的 income_statement.basic_eps 字段)
        - EBITDA 无 DA 字段暴露 → EV-EBITDA model 由 InsufficientDataForModelError 自然 skip
        - forecast_growth / company_beta from state (Task 14 字段;DataCollector 未 wire
          → 默认 None,DCF helper 走 historical fallback)

        核心 source 任一缺失 → return None (Analyst 占位行为兼容,不破现有 e2e)。
        部分 model skip 在 ValuationCalculator 内部处理 (skipped_models 不入 schema)。
        """
        tool_outputs = _index_tool_results(state.tool_results)

        # 核心 source — 任一缺核心数据则全 skip valuation
        stock_quote = tool_outputs.get("get_stock_quote")
        daily_basic = tool_outputs.get("get_daily_basic")
        financials = tool_outputs.get("get_financials")
        balance_sheet = tool_outputs.get("get_balance_sheet")

        if not all([stock_quote, daily_basic, financials, balance_sheet]):
            logger.debug(
                "v1.x A5a: valuation skip - missing core tool_results "
                "(quote=%s, daily_basic=%s, financials=%s, balance=%s)",
                stock_quote is not None,
                daily_basic is not None,
                financials is not None,
                balance_sheet is not None,
            )
            return None

        # Optional sources
        cashflow = tool_outputs.get("get_cashflow")
        pe_history = tool_outputs.get("get_pe_history")

        # === Industry classification (heuristic from user_message + target_entity) ===
        industry_hint = f"{state.target_entity or ''} {state.user_message or ''}"
        industry_classification = normalize_industry(industry_hint)

        # === Company fundamentals: eps / bvps via daily_basic + price reverse ===
        # daily_basic.pe 和 daily_basic.pb 已经隐含 eps / bvps:
        # eps = price / pe, bvps = price / pb
        price = _safe_float(stock_quote, "price")
        pe = _safe_float(daily_basic, "pe")
        pb = _safe_float(daily_basic, "pb")
        total_mv = _safe_float(daily_basic, "total_mv")  # 单位:万元 (tushare 惯例)

        if price is None or price <= 0:
            logger.debug("v1.x A5a: valuation skip - invalid price=%s", price)
            return None

        # eps reverse derive: pe>0 才有意义
        if pe is None or pe <= 0:
            logger.debug("v1.x A5a: valuation skip - invalid pe=%s (亏损 / 数据缺)", pe)
            return None
        eps = price / pe

        # bvps reverse derive
        if pb is None or pb <= 0:
            logger.debug("v1.x A5a: valuation skip - invalid pb=%s", pb)
            return None
        bvps = price / pb

        # shares_outstanding from total_mv (万元) / price (元) → shares (万股 → 股)
        if total_mv is None or total_mv <= 0:
            logger.debug("v1.x A5a: valuation skip - invalid total_mv=%s", total_mv)
            return None
        # total_mv (万元) = price (元/股) × shares (万股) → shares (万股) = total_mv / price
        # 转股 (单位股) → ×10000
        shares_outstanding = (total_mv / price) * 10000.0

        # === Industry valuation comparables ===
        # PE: 用 pe_history.median_pe 作为可比 fallback (narrative 阶段标注 limit)
        # 不可用 → 退用 daily_basic.pe (单点 → avg=median=pe 自身)
        industry_pe_avg: float
        industry_pe_median: float
        if pe_history is not None:
            median_pe = _safe_float(pe_history, "median_pe")
            if median_pe is not None and median_pe > 0:
                industry_pe_median = median_pe
                # avg 用 pe_history 的 min/max 均值或 fall back 到 median
                min_pe = _safe_float(pe_history, "min_pe") or median_pe
                max_pe = _safe_float(pe_history, "max_pe") or median_pe
                industry_pe_avg = (
                    (min_pe + max_pe) / 2.0 if (min_pe > 0 and max_pe > 0) else median_pe
                )
            else:
                industry_pe_avg = industry_pe_median = pe
        else:
            industry_pe_avg = industry_pe_median = pe

        # PB: 单点 fallback (信号弱 — 没真行业可比 tool)
        # 用 daily_basic.pb 自身 ±5% 作 bracket
        industry_pb_avg = pb * 1.0
        industry_pb_median = pb * 1.0

        # EV/EBITDA: 同样信号弱;tushare 缺 EBITDA 真值,让 EV-EBITDA 自然 skip
        # 给 0 占位 → compute_ev_ebitda_value raise InsufficientDataForModelError
        industry_ev_ebitda_avg = 0.0
        industry_ev_ebitda_median = 0.0

        # === Balance-sheet derived signals ===
        total_assets = _safe_float(balance_sheet, "total_assets")
        total_liab = _safe_float(balance_sheet, "total_liab")
        net_debt: float
        debt_to_equity: float
        if total_assets is not None and total_liab is not None and total_assets > total_liab > 0:
            equity = total_assets - total_liab
            debt_to_equity = total_liab / equity if equity > 0 else 0.0
            # net_debt = total_liab - cash (cash 不直接暴露 → 用 total_liab 作上界 approx)
            net_debt = total_liab
        else:
            debt_to_equity = 0.0
            net_debt = 0.0

        # EBITDA: 真值缺 (无 DA 字段) → 0 让 EV-EBITDA 自然 skip
        ebitda = 0.0

        # === DCF inputs ===
        # free_cash_flow_base: cashflow.n_cashflow_act 作 OCF proxy (无 capex 字段;OCF≈FCF coarse)
        free_cash_flow_base: float = 0.0
        if cashflow is not None:
            n_cashflow_act = _safe_float(cashflow, "n_cashflow_act")
            if n_cashflow_act is not None and n_cashflow_act > 0:
                free_cash_flow_base = n_cashflow_act

        # historical_growth: tushare income / financials 只暴露最近期 revenue,
        # 无法构造历史增速 list → 留空 (DCF helper 用 forecast_growth fallback,
        # 或 base scenario 时 forecast_growth None + historical 空 → DCF 自然 skip)
        historical_growth: list[float] = []

        # forecast_growth: Task 14 字段;DataCollector 未 wire → 默认 None
        forecast_growth = state.forecast_growth

        # company_beta: 同 Task 14 留位;price_history_for_beta 未收集 → None
        company_beta: float | None = None

        # === Industry DCF defaults ===
        industry_wacc, industry_terminal = get_industry_dcf_defaults(industry_classification)

        return ValuationInputs(
            industry_classification=industry_classification,
            industry_pe_avg=industry_pe_avg,
            industry_pe_median=industry_pe_median,
            industry_pb_avg=industry_pb_avg,
            industry_pb_median=industry_pb_median,
            industry_ev_ebitda_avg=industry_ev_ebitda_avg,
            industry_ev_ebitda_median=industry_ev_ebitda_median,
            industry_baseline_wacc=industry_wacc,
            industry_terminal_growth=industry_terminal,
            eps=eps,
            book_value_per_share=bvps,
            ebitda=ebitda,
            net_debt=net_debt,
            shares_outstanding=shares_outstanding,
            free_cash_flow_base=free_cash_flow_base,
            historical_growth=historical_growth,
            forecast_growth=forecast_growth,
            company_beta=company_beta,
            debt_to_equity=debt_to_equity,
        )


# ---------------------------------------------------------------------------
# Helper functions for _build_valuation_inputs_from_state
# v1.x A5a follow-up #1
# ---------------------------------------------------------------------------


def _index_tool_results(tool_results: list[ToolResult]) -> dict[str, dict[str, Any]]:
    """Build tool_name → output dict index from tool_results list.

    Only successful results with non-None output included. Last occurrence wins
    on duplicate tool_name (rare; DataCollector typically calls each tool once).
    """
    index: dict[str, dict[str, Any]] = {}
    for tr in tool_results:
        if not tr.success or tr.output is None:
            continue
        # Skip tool error outputs (which set output={"ts_code": ..., "error": "no data"})
        if "error" in tr.output:
            continue
        index[tr.tool_name] = tr.output
    return index


def _safe_float(output: dict[str, Any] | None, key: str) -> float | None:
    """Defensive float extraction. Return None if output is None, key missing,
    value is None / NaN / inf, or coercion fails."""
    if output is None:
        return None
    raw = output.get(key)
    if raw is None:
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    return v
