"""信贷调查报告 Pydantic schema(B-1 use case)。

设计 ref: docs/superpowers/specs/2026-05-03-v0.8.2-credit-research-report-design.md § 2
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ── 通用 dataclass ─────────────────────────────────────────────────────────────


class FinancialMetric(BaseModel):
    """单条财务指标。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="指标名,如 '营业收入' / '资产负债率'")
    value: str = Field(description="指标值,如 '150 亿元' / '12.5%'(字符串,不强制单位)")
    period: str = Field(description="期间,如 '2024 H1' / '2024 全年'")
    yoy_change: str | None = Field(default=None, description="同比变化,如 '同比 +15%'")


class RiskItem(BaseModel):
    """单条风险项。"""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(description="风险标题")
    description: str = Field(description="风险描述")
    severity: Literal["low", "medium", "high"] = Field(description="单项严重度")
    mitigations: list[str] = Field(default_factory=list, description="可缓释措施")


# ── Section schemas ────────────────────────────────────────────────────────────


class CompanyOverview(BaseModel):
    """§ 1 基本信息。"""

    model_config = ConfigDict(extra="forbid")

    narrative: str = Field(description="100-300 字综述")
    unified_credit_code: str | None = Field(default=None, description="统一社会信用代码")
    registered_capital: str | None = Field(default=None, description="注册资本")
    main_business: str = Field(description="主营业务一句话")
    controlling_shareholder: str | None = Field(default=None, description="实际控制人")
    listing_status: str | None = Field(default=None, description="上市/非上市 + 板块")
    evidence: list[str] = Field(min_length=1, description="引用的 chunk_id 列表(至少 1 个)")


class LegalQualification(BaseModel):
    """§ 2 主体资格。"""

    model_config = ConfigDict(extra="forbid")

    narrative: str = Field(description="200-400 字综述")
    legal_status: str = Field(description="法律主体合规情况")
    business_qualifications: list[str] = Field(description="经营资质列表(空 list 也行)")
    adverse_records: list[str] = Field(description="不良记录(空 list 也行)")
    evidence: list[str] = Field(min_length=1)


class FinancialAnalysis(BaseModel):
    """§ 3 财务分析。"""

    model_config = ConfigDict(extra="forbid")

    narrative: str = Field(description="400-800 字深度分析")
    key_metrics: list[FinancialMetric] = Field(description="关键财务指标")
    solvency_analysis: str = Field(description="偿债能力")
    profitability_analysis: str = Field(description="盈利能力")
    cash_flow_analysis: str = Field(description="现金流分析")
    year_over_year_summary: str | None = Field(default=None, description="同比变化(若多年数据)")
    evidence: list[str] = Field(min_length=1)


class IndustryAnalysis(BaseModel):
    """§ 4 行业分析。"""

    model_config = ConfigDict(extra="forbid")

    narrative: str = Field(description="300-600 字")
    industry_name: str = Field(description="所属行业")
    industry_outlook: str = Field(description="景气度判断")
    competitive_position: str = Field(description="在行业中的竞争地位")
    key_competitors: list[str] = Field(description="主要竞争对手(空 list 也行)")
    policy_impact: str = Field(description="相关政策影响")
    evidence: list[str] = Field(min_length=1)


class RiskAssessment(BaseModel):
    """§ 5 风险评估。"""

    model_config = ConfigDict(extra="forbid")

    narrative: str = Field(description="300-500 字")
    operational_risks: list[RiskItem] = Field(description="经营风险列表(空 list 也行)")
    financial_risks: list[RiskItem] = Field(description="财务风险列表")
    industry_risks: list[RiskItem] = Field(description="行业风险列表")
    compliance_risks: list[RiskItem] = Field(description="合规风险列表")
    overall_risk_level: Literal["low", "medium", "high", "very_high"] = Field(
        description="整体风险等级"
    )
    evidence: list[str] = Field(min_length=1)


class CreditRecommendation(BaseModel):
    """§ 6 信贷建议。"""

    model_config = ConfigDict(extra="forbid")

    narrative: str = Field(description="200-400 字综合建议")
    decision: Literal["approve", "reject", "approve_with_conditions"] = Field(
        description="决策建议"
    )
    recommended_credit_limit: str | None = Field(default=None, description="建议额度")
    recommended_term: str | None = Field(default=None, description="建议期限")
    recommended_rate_range: str | None = Field(default=None, description="建议利率区间")
    guarantee_requirements: list[str] = Field(description="担保要求(空 list 也行)")
    conditions: list[str] = Field(description="附加条件(approve_with_conditions 时填)")
    evidence: list[str] = Field(min_length=1)


# ── 主 schema ──────────────────────────────────────────────────────────────────


class CreditInvestigationReport(BaseModel):
    """信贷调查报告(B-1 use case 主输出)。"""

    model_config = ConfigDict(extra="forbid")

    # Header
    company_name: str = Field(description="企业名")
    request_id: str = Field(description="关联 trace request_id")
    generated_at: datetime = Field(description="生成时间")

    # Sections(全必填)
    company_overview: CompanyOverview
    legal_qualification: LegalQualification
    financial_analysis: FinancialAnalysis
    industry_analysis: IndustryAnalysis
    risk_assessment: RiskAssessment
    credit_recommendation: CreditRecommendation
