"""L0 — IndustryModelRouter (deterministic table + LLM override)."""

from __future__ import annotations

import pytest
from app.agents.investment_dd_schema import ValuationModel


def test_router_lookup_consumer_returns_pe_dcf() -> None:
    from app.agents.industry_model_router import lookup_default_models

    models = lookup_default_models("白酒")
    assert ValuationModel.PE in models
    assert ValuationModel.DCF in models


def test_router_lookup_bank_returns_pb_ev_ebitda() -> None:
    from app.agents.industry_model_router import lookup_default_models

    models = lookup_default_models("银行")
    assert ValuationModel.PB in models
    assert ValuationModel.EV_EBITDA in models
    assert ValuationModel.DCF not in models


def test_router_lookup_telecom_returns_ev_ebitda_dcf() -> None:
    from app.agents.industry_model_router import lookup_default_models

    models = lookup_default_models("电信运营")
    assert ValuationModel.EV_EBITDA in models
    assert ValuationModel.DCF in models


def test_router_unknown_industry_returns_default() -> None:
    from app.agents.industry_model_router import lookup_default_models

    models = lookup_default_models("某个新概念AI")
    # _default fallback = [PE, DCF]
    assert ValuationModel.PE in models
    assert ValuationModel.DCF in models


def test_router_mapping_table_all_values_valid_enum() -> None:
    """全表 round-trip:每个 value 都是合法 ValuationModel enum"""
    from app.agents.industry_model_router import INDUSTRY_VALUATION_MAPPING

    for industry, models in INDUSTRY_VALUATION_MAPPING.items():
        assert len(models) >= 1, f"{industry} 必须至少 1 个 model"
        assert all(isinstance(m, ValuationModel) for m in models), industry


def test_router_override_replaces_default() -> None:
    from app.agents.industry_model_router import RouterOverride, apply_llm_override

    default = [ValuationModel.PE, ValuationModel.DCF]
    override = RouterOverride(
        override_models=[ValuationModel.PE, ValuationModel.EV_EBITDA, ValuationModel.DCF],
        reasoning="腾讯既是消费又是平台型科技,加 EV/EBITDA 反映高负债阶段",
        confidence="medium",
    )
    final, reasoning = apply_llm_override(default, override)
    assert final == override.override_models
    assert reasoning == override.reasoning


def test_router_no_override_keeps_default() -> None:
    from app.agents.industry_model_router import apply_llm_override

    default = [ValuationModel.PE, ValuationModel.DCF]
    final, reasoning = apply_llm_override(default, None)
    assert final == default
    assert reasoning is None


def test_router_override_schema_validation() -> None:
    """override_models min_length=1, max_length=4; reasoning max_length=200"""
    from app.agents.industry_model_router import RouterOverride
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        RouterOverride(override_models=[], reasoning="x", confidence="high")
    with pytest.raises(ValidationError):
        RouterOverride(override_models=[ValuationModel.PE], reasoning="x" * 201, confidence="high")
