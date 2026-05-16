"""v1.x A5a: IndustryModelRouter.

第一层 deterministic mapping(industry_code → active_models)覆盖 80% 标准行业。
第二层 LLM analyst judgment override(腾讯 / 美团 跨界 case),给 ≤200 char reasoning。
本期(v1.x A5a)Analyst 默认不调 LLM override(留 hook 给 v1.x++ override 真接入)。

设计原则(spec § 5):
- deterministic mapping 表覆盖主流行业,保证 80% case 不调 LLM
- 边界 case(业务模式跨界 / 新概念股)由 LLM analyst 在 narrative 阶段判断 + override
- override 必带 reasoning(审计 trail)+ confidence(高 = 强信号)

spec ref: 2026-05-16-v1.x-multi-valuation-cross-check-design.md § 5
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agents.investment_dd_schema import ValuationModel

__all__ = [
    "INDUSTRY_VALUATION_MAPPING",
    "RouterOverride",
    "lookup_default_models",
    "apply_llm_override",
]


# 行业 → 默认激活模型 mapping。覆盖 tushare 常见 industry_code。
# 设计原则:每个行业仅放"真有信号密度"的模型,不冗余(spec § 4 信号密度论证)。
INDUSTRY_VALUATION_MAPPING: dict[str, list[ValuationModel]] = {
    # 消费 / 品牌
    "白酒": [ValuationModel.PE, ValuationModel.DCF],
    "食品饮料": [ValuationModel.PE, ValuationModel.DCF],
    "家电": [ValuationModel.PE, ValuationModel.DCF],
    "服装": [ValuationModel.PE, ValuationModel.DCF],
    # 科技 / 成长
    "软件服务": [ValuationModel.PE, ValuationModel.DCF],
    "半导体": [ValuationModel.PE, ValuationModel.DCF],
    "互联网": [ValuationModel.PE, ValuationModel.DCF],
    # 金融
    "银行": [ValuationModel.PB, ValuationModel.EV_EBITDA],
    "保险": [ValuationModel.PB],
    "证券": [ValuationModel.PB, ValuationModel.PE],
    # 地产 / 周期
    "房地产开发": [ValuationModel.PB],
    "钢铁": [ValuationModel.EV_EBITDA, ValuationModel.PB],
    "煤炭": [ValuationModel.EV_EBITDA, ValuationModel.PB],
    "化工": [ValuationModel.EV_EBITDA, ValuationModel.PB],
    # 重资本 / 公用
    "电信运营": [ValuationModel.EV_EBITDA, ValuationModel.DCF],
    "电力": [ValuationModel.PB, ValuationModel.EV_EBITDA],
    "公用事业": [ValuationModel.PB],
    # Fallback
    "_default": [ValuationModel.PE, ValuationModel.DCF],
}


class RouterOverride(BaseModel):
    """LLM analyst 在 deterministic mapping 之上的 judgment override 输出。

    Analyst 看公司 narrative,如果发现"跨界 / 业务模式特殊",可 override 默认 models。
    必须给 reasoning(审计 trail) + confidence(高 = 强信号,低 = 拍脑袋)。

    本期(v1.x A5a)schema 已就位但 Analyst 默认 override=None,留 hook 给 v1.x++ 真接入。
    """

    model_config = ConfigDict(frozen=True)

    override_models: list[ValuationModel] = Field(min_length=1, max_length=4)
    reasoning: str = Field(max_length=200)
    confidence: Literal["high", "medium", "low"]


def lookup_default_models(industry_classification: str) -> list[ValuationModel]:
    """查表;未命中 → _default fallback。"""
    return INDUSTRY_VALUATION_MAPPING.get(
        industry_classification, INDUSTRY_VALUATION_MAPPING["_default"]
    )


def apply_llm_override(
    default_models: list[ValuationModel],
    override: RouterOverride | None,
) -> tuple[list[ValuationModel], str | None]:
    """if override is not None → 使用 override.override_models + reasoning。
    else → 保留 default,reasoning=None。
    """
    if override is None:
        return default_models, None
    return list(override.override_models), override.reasoning
