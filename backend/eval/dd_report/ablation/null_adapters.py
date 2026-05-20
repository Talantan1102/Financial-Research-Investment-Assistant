"""Null adapters for V1 (无 RAG) + SingleAgentPipeline for V2 (无 multi-agent).

spec § 4.7 决策 7: 用 swap 组件方式量化每个 pipeline 组件的贡献。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.agents.investment_dd_schema import (
    DEFAULT_DISCLAIMER,
    FinancialAnalysis,
    IndustryAnalysis,
    InvestmentDueDiligenceReport,
    InvestmentRecommendation,
    LegalQualification,
    PriceRange,
    RiskAssessment,
    TargetOverview,
    ValuationAnalysis,
)


@dataclass
class NullKBAdapter:
    """V1 ablation: search 永远返 [] (模拟无 RAG path)."""

    def search(self, query: str, k: int = 10, **kwargs: Any) -> list[Any]:
        return []


@dataclass
class SingleAgentPipeline:
    """V2 ablation: 单 prompt 一次性出全报告 (无 multi-agent 编排).

    用单 LLM call (evaluator_client.chat) 让模型直接输出整个
    InvestmentDueDiligenceReport JSON。Pydantic parse 失败时返回最小 fallback
    stub (此变体的目标就是与 V0 对比, 失败本身也是数据点)。
    """

    tushare_adapter: Any
    kb_adapter: Any
    evaluator_client: Any

    def __call__(self, target_name: str, target_ts_code: str) -> InvestmentDueDiligenceReport:
        prompt = (
            f"你是金融分析师, 直接出 {target_name} ({target_ts_code}) 的 "
            f"InvestmentDueDiligenceReport JSON, 包含全部 6 section 字段, "
            f"严格匹配 schema。不要思考过程, 直接 JSON。"
        )
        try:
            raw = self.evaluator_client.chat(prompt=prompt)
            data = json.loads(raw)
            return InvestmentDueDiligenceReport.model_validate(data)
        except Exception:
            return _minimal_stub(target_name, target_ts_code)


def _minimal_stub(target_name: str, target_ts_code: str) -> InvestmentDueDiligenceReport:
    """V2 fallback stub — 让 backtest 走通, metric 评分自动 vacuous."""
    return InvestmentDueDiligenceReport(
        target_name=target_name,
        target_ts_code=target_ts_code,
        request_id="ablation-v2-stub",
        generated_at=datetime.now(UTC),
        target_overview=TargetOverview(
            narrative="(V2 single-agent stub)",
            main_business="N/A",
        ),
        legal_qualification=LegalQualification(
            narrative="(stub)",
            legal_status="N/A",
            business_qualifications=[],
            adverse_records=[],
        ),
        financial_analysis=FinancialAnalysis(
            narrative="(stub)",
            key_metrics=[],
            profitability_analysis="N/A",
            growth_analysis="N/A",
            return_analysis="N/A",
            cash_flow_analysis="N/A",
            valuation_analysis=ValuationAnalysis(narrative="N/A"),
        ),
        industry_analysis=IndustryAnalysis(
            narrative="(stub)",
            industry_name="N/A",
            industry_outlook="N/A",
            competitive_position="N/A",
            key_competitors=[],
            policy_impact="N/A",
        ),
        risk_assessment=RiskAssessment(
            narrative="(stub)",
            market_risk=[],
            growth_risk=[],
            event_risk=[],
            valuation_risk=[],
            overall_risk_level="medium",
        ),
        investment_recommendation=InvestmentRecommendation(
            narrative="(stub)",
            recommendation="recommend_hold",
            recommended_position_size_pct=0.0,
            recommended_holding_period="medium_term",
            recommended_entry_price_range=PriceRange(low=0, high=0),
            recommended_stop_loss_price=0,
            estimated_target_price_range=PriceRange(low=0, high=0),
            position_management_conditions=[],
        ),
        disclaimer=DEFAULT_DISCLAIMER,
    )
