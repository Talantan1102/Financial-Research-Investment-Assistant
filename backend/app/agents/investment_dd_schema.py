"""投资标的尽调报告 Pydantic schema (B-1 use case, v0.8.4).

设计 ref: docs/superpowers/specs/2026-05-04-v0.8.4-b1-single-deep-design.md § 3
"""

from __future__ import annotations

from datetime import datetime
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

# ── 免责声明文本(固定)────────────────────────────────────────────────────────

DEFAULT_DISCLAIMER: Final[str] = (
    "本报告由 AI 模型(LLM)基于截至生成时间的公开数据辅助生成,"
    "仅供客户经理参考,不构成投资建议或具体买卖指令。"
    "投资决策应由客户经理结合客户具体情况及最新市场状况审慎判断。"
    "模型可能存在数据滞后、推理偏差或表述不准确的情况,"
    "使用前请验证关键数据的真实性。市场有风险,投资需谨慎。"
)


# ── 通用 dataclass ─────────────────────────────────────────────────────────────


class PriceRange(BaseModel):
    """价格区间。"""

    model_config = ConfigDict(extra="ignore")

    low: float = Field(description="区间下限")
    high: float = Field(description="区间上限")


class FinancialMetric(BaseModel):
    """单条财务指标。"""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(description="指标名,如 '营业收入' / '资产负债率'")
    value: str = Field(description="指标值,如 '150 亿元' / '12.5%'(字符串,不强制单位)")
    period: str = Field(description="期间,如 '2024 H1' / '2024 全年'")
    yoy_change: str | None = Field(default=None, description="同比变化,如 '同比 +15%'")


class RiskItem(BaseModel):
    """单条风险项。"""

    model_config = ConfigDict(extra="ignore")

    title: str = Field(description="风险标题")
    description: str = Field(description="风险描述")
    severity: Literal["low", "medium", "high"] = Field(description="单项严重度")
    mitigations: list[str] = Field(default_factory=list, description="可缓释措施")


class ValuationAnalysis(BaseModel):
    """估值分析子模块(FinancialAnalysis § 3 新增)。"""

    model_config = ConfigDict(extra="ignore")

    narrative: str = Field(description="估值分析综述")
    pe_historical_percentile: str | None = Field(
        default=None, description="PE 历史百分位,如 '近 5 年 30 分位'"
    )
    # v0.8.5 forward concern 1 — numeric sibling for classify_recommendation.
    # 0.0 ≤ x ≤ 1.0 (e.g. 0.30 = 30 分位). Existing str field stays for
    # narrative use; downstream extractor prefers numeric when present, falls
    # back to regex-parsing the str, then to 0.5 mid-cap default.
    pe_historical_percentile_value: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="PE 历史百分位的数值化(0.0-1.0,如 0.30 = 近 5 年 30 分位)",
    )
    dcf_valuation: str | None = Field(default=None, description="DCF 估值结论")
    peer_comparison: str | None = Field(default=None, description="同业估值对比")


# ── Section schemas ────────────────────────────────────────────────────────────


class TargetOverview(BaseModel):
    """§ 1 标的基本信息(含估值快照)。"""

    model_config = ConfigDict(extra="ignore")

    narrative: str = Field(description="100-300 字综述")
    registered_capital: str | None = Field(default=None, description="注册资本")
    main_business: str = Field(description="主营业务一句话")
    controlling_shareholder: str | None = Field(default=None, description="实际控制人")
    listing_status: str | None = Field(default=None, description="上市/非上市 + 板块")
    # 估值快照(新增)
    current_pe: float | None = Field(default=None, description="当前市盈率(PE)")
    current_pb: float | None = Field(default=None, description="当前市净率(PB)")
    current_market_cap: float | None = Field(default=None, description="当前总市值(亿元)")
    dividend_yield: float | None = Field(default=None, description="股息率(%)")
    evidence: list[str] = Field(
        default_factory=list,
        description="引用的 chunk_id 列表(允许空 — Critic factuality scorer 扣分代替 schema 强制)",
    )


class LegalQualification(BaseModel):
    """§ 2 主体资格。"""

    model_config = ConfigDict(extra="ignore")

    narrative: str = Field(description="200-400 字综述")
    legal_status: str = Field(description="法律主体合规情况")
    business_qualifications: list[str] = Field(description="经营资质列表(空 list 也行)")
    adverse_records: list[str] = Field(description="不良记录(空 list 也行)")
    evidence: list[str] = Field(
        default_factory=list,
        description="引用的 chunk_id 列表(允许空 — Critic factuality scorer 扣分代替 schema 强制)",
    )


class FinancialAnalysis(BaseModel):
    """§ 3 财务分析(投资视角,含估值分析)。"""

    model_config = ConfigDict(extra="ignore")

    narrative: str = Field(description="400-800 字深度分析")
    key_metrics: list[FinancialMetric] = Field(description="关键财务指标")
    profitability_analysis: str = Field(description="盈利质量分析")
    growth_analysis: str = Field(description="成长性分析")
    return_analysis: str = Field(description="投资回报分析(ROE/ROIC 等)")
    cash_flow_analysis: str = Field(description="现金流分析")
    valuation_analysis: ValuationAnalysis = Field(description="估值分析(PE/PB/DCF/同业)")
    # v0.8.5 forward concern 3 — wires asset_liability_warning red-line in
    # writer.post_process. Prior to this field the str check
    # `fa.get("debt_ratio_assessment") in {"警戒","高风险"}` was dead code (field
    # did not exist on schema, LLM never emitted it).
    debt_ratio_assessment: Literal["健康", "一般", "警戒", "高风险"] | None = Field(
        default=None,
        description="资产负债率评估(用于触发 asset_liability_warning red-line)",
    )
    year_over_year_summary: str | None = Field(default=None, description="同比变化(若多年数据)")
    evidence: list[str] = Field(
        default_factory=list,
        description="引用的 chunk_id 列表(允许空 — Critic factuality scorer 扣分代替 schema 强制)",
    )


class IndustryAnalysis(BaseModel):
    """§ 4 行业分析。"""

    model_config = ConfigDict(extra="ignore")

    narrative: str = Field(description="300-600 字")
    industry_name: str = Field(description="所属行业")
    industry_outlook: str = Field(description="景气度判断")
    competitive_position: str = Field(description="在行业中的竞争地位")
    key_competitors: list[str] = Field(description="主要竞争对手(空 list 也行)")
    policy_impact: str = Field(description="相关政策影响")
    evidence: list[str] = Field(
        default_factory=list,
        description="引用的 chunk_id 列表(允许空 — Critic factuality scorer 扣分代替 schema 强制)",
    )


class RiskAssessment(BaseModel):
    """§ 5 风险评估(投资视角风险维度)。"""

    model_config = ConfigDict(extra="ignore")

    narrative: str = Field(description="300-500 字")
    market_risk: list[RiskItem] = Field(description="市场风险(beta / 流动性)")
    growth_risk: list[RiskItem] = Field(description="成长不达预期风险")
    event_risk: list[RiskItem] = Field(description="黑天鹅/事件风险")
    valuation_risk: list[RiskItem] = Field(description="估值过高风险")
    overall_risk_level: Literal["low", "medium", "high", "very_high"] = Field(
        description="整体风险等级"
    )
    evidence: list[str] = Field(
        default_factory=list,
        description="引用的 chunk_id 列表(允许空 — Critic factuality scorer 扣分代替 schema 强制)",
    )


class InvestmentRecommendation(BaseModel):
    """§ 6 投资建议(5 档卖方研报标准化术语)。"""

    model_config = ConfigDict(extra="ignore")

    narrative: str = Field(description="200-400 字综合建议")
    recommendation: Literal[
        "recommend_buy",
        "recommend_overweight",
        "recommend_hold",
        "recommend_underweight",
        "recommend_sell",
    ] = Field(description="投资建议评级")
    recommended_position_size_pct: float = Field(
        description="建议仓位占 client_total_aum 的百分比(%)"
    )
    recommended_holding_period: Literal["short_term", "medium_term", "long_term"] = Field(
        description="建议持有期限"
    )
    recommended_entry_price_range: PriceRange = Field(description="建议买入价格区间")
    recommended_stop_loss_price: float = Field(description="建议止损价格")
    estimated_target_price_range: PriceRange = Field(description="目标价格区间(estimated 降权)")
    position_management_conditions: list[str] = Field(description="加仓/减仓触发条件(空 list 也行)")
    evidence: list[str] = Field(
        default_factory=list,
        description="引用的 chunk_id 列表(允许空 — Critic factuality scorer 扣分代替 schema 强制)",
    )


# ── 主 schema ──────────────────────────────────────────────────────────────────


class InvestmentDueDiligenceReport(BaseModel):
    """投资标的尽调报告(B-1 use case 主输出,v0.8.4)。"""

    model_config = ConfigDict(extra="ignore")

    # 主键 + snapshot
    target_name: str = Field(description="标的全称")
    target_ts_code: str = Field(description="股票代码,如 600519.SH")
    request_id: str = Field(description="关联 trace request_id")
    generated_at: datetime = Field(description="生成时间")
    target_close_price_at_gen: float | None = Field(default=None, description="生成时收盘价")
    target_market_cap_at_gen: float | None = Field(default=None, description="生成时总市值(亿元)")

    # 6 sections
    target_overview: TargetOverview
    legal_qualification: LegalQualification
    financial_analysis: FinancialAnalysis
    industry_analysis: IndustryAnalysis
    risk_assessment: RiskAssessment
    investment_recommendation: InvestmentRecommendation

    # 免责声明
    disclaimer: str = Field(default=DEFAULT_DISCLAIMER, description="AI 辅助生成免责声明")
