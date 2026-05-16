"""v1.x A5a: ValuationCalculator orchestrator.

flow:
1. IndustryModelRouter (lookup_default + apply_override) → active_models
2. 对每个 active model 调对应 Python helper:
   - PE → compute_pe_value
   - PB → compute_pb_value
   - EV_EBITDA → compute_ev_ebitda_value
   - DCF → growth_trajectory × 3 (base/bull/bear) + compute_dcf_value × 3 + sensitivity
3. helper raise InsufficientDataForModelError → skip, 记 skipped_models[model] = reason
4. analyze_consistency on collected non-None values (DCF 只用 dcf_base)

输出 ValuationResult dataclass。caller (Analyst node, Task 15) 拷贝 schema 字段到
ValuationAnalysis; skipped_models 不入 schema (仅 internal trace)。

spec ref: 2026-05-16-v1.x-multi-valuation-cross-check-design.md § 8
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.agents.industry_model_router import (
    RouterOverride,
    apply_llm_override,
    lookup_default_models,
)
from app.agents.investment_dd_schema import ValuationModel
from app.agents.valuation_helpers.consistency import analyze_consistency
from app.agents.valuation_helpers.dcf import (
    compute_company_wacc,
    compute_dcf_sensitivity,
    compute_dcf_value,
    compute_growth_trajectory,
)
from app.agents.valuation_helpers.ev_ebitda import compute_ev_ebitda_value
from app.agents.valuation_helpers.exceptions import InsufficientDataForModelError
from app.agents.valuation_helpers.pb import compute_pb_value
from app.agents.valuation_helpers.pe import compute_pe_value

__all__ = ["ValuationInputs", "ValuationResult", "calculate_valuations"]


@dataclass
class ValuationInputs:
    industry_classification: str
    industry_pe_avg: float
    industry_pe_median: float
    industry_pb_avg: float
    industry_pb_median: float
    industry_ev_ebitda_avg: float
    industry_ev_ebitda_median: float
    industry_baseline_wacc: float
    industry_terminal_growth: float

    eps: float
    book_value_per_share: float
    ebitda: float
    net_debt: float
    shares_outstanding: float
    free_cash_flow_base: float
    historical_growth: list[float]
    forecast_growth: float | None
    company_beta: float | None
    debt_to_equity: float


@dataclass
class ValuationResult:
    active_models: list[ValuationModel]
    router_override_reasoning: str | None = None
    pe_value: float | None = None
    pb_value: float | None = None
    ev_ebitda_value: float | None = None
    dcf_base: float | None = None
    dcf_bull: float | None = None
    dcf_bear: float | None = None
    dcf_sensitivity: list[list[float]] | None = None
    valuation_consistency: Literal["consistent", "moderate", "severe"] | None = None
    skipped_models: dict[ValuationModel, str] = field(default_factory=dict)


def calculate_valuations(
    inputs: ValuationInputs,
    router_override: RouterOverride | None,
) -> ValuationResult:
    default_models = lookup_default_models(inputs.industry_classification)
    active_models, override_reasoning = apply_llm_override(default_models, router_override)

    result = ValuationResult(
        active_models=list(active_models),
        router_override_reasoning=override_reasoning,
    )

    for model in active_models:
        try:
            if model == ValuationModel.PE:
                result.pe_value = compute_pe_value(
                    eps=inputs.eps,
                    industry_pe_avg=inputs.industry_pe_avg,
                    industry_pe_median=inputs.industry_pe_median,
                )
            elif model == ValuationModel.PB:
                result.pb_value = compute_pb_value(
                    book_value_per_share=inputs.book_value_per_share,
                    industry_pb_avg=inputs.industry_pb_avg,
                    industry_pb_median=inputs.industry_pb_median,
                )
            elif model == ValuationModel.EV_EBITDA:
                result.ev_ebitda_value = compute_ev_ebitda_value(
                    ebitda=inputs.ebitda,
                    net_debt=inputs.net_debt,
                    shares_outstanding=inputs.shares_outstanding,
                    industry_ev_ebitda_avg=inputs.industry_ev_ebitda_avg,
                    industry_ev_ebitda_median=inputs.industry_ev_ebitda_median,
                )
            elif model == ValuationModel.DCF:
                try:
                    wacc = compute_company_wacc(
                        industry_baseline_wacc=inputs.industry_baseline_wacc,
                        company_beta=inputs.company_beta,
                        debt_to_equity=inputs.debt_to_equity,
                    )
                    # 3 场景
                    for scenario_name in ("base", "bull", "bear"):
                        trajectory = compute_growth_trajectory(
                            historical_growth=inputs.historical_growth,
                            forecast_growth=inputs.forecast_growth,
                            industry_terminal=inputs.industry_terminal_growth,
                            scenario=scenario_name,
                        )
                        price = compute_dcf_value(
                            free_cash_flow_base=inputs.free_cash_flow_base,
                            shares_outstanding=inputs.shares_outstanding,
                            growth_trajectory=trajectory,
                            terminal_growth=inputs.industry_terminal_growth,
                            wacc=wacc,
                        )
                        if scenario_name == "base":
                            result.dcf_base = price
                        elif scenario_name == "bull":
                            result.dcf_bull = price
                        elif scenario_name == "bear":
                            result.dcf_bear = price

                    # sensitivity (基于 base 场景的 trajectory)
                    base_trajectory = compute_growth_trajectory(
                        historical_growth=inputs.historical_growth,
                        forecast_growth=inputs.forecast_growth,
                        industry_terminal=inputs.industry_terminal_growth,
                        scenario="base",
                    )
                    result.dcf_sensitivity = compute_dcf_sensitivity(
                        free_cash_flow_base=inputs.free_cash_flow_base,
                        shares_outstanding=inputs.shares_outstanding,
                        growth_trajectory=base_trajectory,
                        base_terminal_growth=inputs.industry_terminal_growth,
                        base_wacc=wacc,
                    )
                except InsufficientDataForModelError:
                    # binary reset: partial DCF state 不留下,避免 caller 语义打架
                    # (dcf_base != None + DCF in skipped_models 共存)
                    result.dcf_base = None
                    result.dcf_bull = None
                    result.dcf_bear = None
                    result.dcf_sensitivity = None
                    raise  # 让外层 except 写 skipped_models[DCF]
        except InsufficientDataForModelError as e:
            result.skipped_models[model] = e.reason

    # consistency: 收集成功的 lens (DCF 用 base 场景)
    valid: dict[str, float] = {}
    if result.pe_value is not None:
        valid["pe"] = result.pe_value
    if result.pb_value is not None:
        valid["pb"] = result.pb_value
    if result.ev_ebitda_value is not None:
        valid["ev_ebitda"] = result.ev_ebitda_value
    if result.dcf_base is not None:
        valid["dcf_base"] = result.dcf_base

    result.valuation_consistency = analyze_consistency(valid)
    return result
