"""L0 — ValuationCalculator orchestrator."""

from __future__ import annotations

from app.agents.industry_model_router import RouterOverride
from app.agents.investment_dd_schema import ValuationModel


def _maotai_inputs():  # noqa: ANN202
    """白酒标准 inputs(茅台)— 行业 PE 25-30, PB 7-9, EBITDA 倍数 18-22, WACC 7%, 永续 2.5%"""
    from app.agents.valuation_calculator import ValuationInputs

    return ValuationInputs(
        industry_classification="白酒",
        industry_pe_avg=30.0,
        industry_pe_median=25.0,
        industry_pb_avg=8.0,
        industry_pb_median=7.0,
        industry_ev_ebitda_avg=22.0,
        industry_ev_ebitda_median=18.0,
        industry_baseline_wacc=0.07,
        industry_terminal_growth=0.025,
        eps=60.0,
        book_value_per_share=250.0,
        ebitda=800e8,
        net_debt=-100e8,
        shares_outstanding=12.5e8,
        free_cash_flow_base=600e8,
        historical_growth=[0.10, 0.12, 0.08, 0.09, 0.10],
        forecast_growth=0.10,
        company_beta=0.9,
        debt_to_equity=0.05,
    )


def test_calculator_maotai_active_models_pe_dcf() -> None:
    """白酒 → router 选 PE + DCF;PB / EV_EBITDA 不应 active."""
    from app.agents.valuation_calculator import calculate_valuations

    result = calculate_valuations(_maotai_inputs(), router_override=None)

    assert ValuationModel.PE in result.active_models
    assert ValuationModel.DCF in result.active_models
    assert ValuationModel.PB not in result.active_models

    assert result.pe_value is not None
    assert result.dcf_base is not None
    assert result.dcf_bull is not None
    assert result.dcf_bear is not None
    assert result.pb_value is None
    assert result.ev_ebitda_value is None


def test_calculator_dcf_scenario_ordering() -> None:
    """对 maotai: dcf_bear < dcf_base < dcf_bull"""
    from app.agents.valuation_calculator import calculate_valuations

    result = calculate_valuations(_maotai_inputs(), router_override=None)
    assert (
        result.dcf_bear is not None and result.dcf_base is not None and result.dcf_bull is not None
    )
    assert result.dcf_bear < result.dcf_base
    assert result.dcf_base < result.dcf_bull


def test_calculator_dcf_sensitivity_matrix_shape() -> None:
    """DCF active → 5×5 matrix"""
    from app.agents.valuation_calculator import calculate_valuations

    result = calculate_valuations(_maotai_inputs(), router_override=None)
    assert result.dcf_sensitivity is not None
    assert len(result.dcf_sensitivity) == 5
    assert all(len(row) == 5 for row in result.dcf_sensitivity)


def test_calculator_consistency_label_set() -> None:
    """白酒 maotai 多 lens 应产生 consistency 标签."""
    from app.agents.valuation_calculator import calculate_valuations

    result = calculate_valuations(_maotai_inputs(), router_override=None)
    assert result.valuation_consistency in {"consistent", "moderate", "severe"}


def test_calculator_override_changes_active_models() -> None:
    """LLM override 把 EV_EBITDA 加进来"""
    from app.agents.valuation_calculator import calculate_valuations

    override = RouterOverride(
        override_models=[ValuationModel.PE, ValuationModel.DCF, ValuationModel.EV_EBITDA],
        reasoning="测试 override",
        confidence="high",
    )
    result = calculate_valuations(_maotai_inputs(), router_override=override)
    assert ValuationModel.EV_EBITDA in result.active_models
    assert result.ev_ebitda_value is not None
    assert result.router_override_reasoning == "测试 override"


def test_calculator_skip_model_on_insufficient_data() -> None:
    """eps=-5 (亏损公司) → PE skip,记录 reason;其它 model 不影响"""
    from app.agents.valuation_calculator import calculate_valuations

    inputs = _maotai_inputs()
    inputs.eps = -5.0  # 亏损
    result = calculate_valuations(inputs, router_override=None)

    assert result.pe_value is None
    assert ValuationModel.PE in result.skipped_models
    assert "eps" in result.skipped_models[ValuationModel.PE].lower()
    # active_models 仍保留 PE(router 选了,helper 跳)
    assert ValuationModel.PE in result.active_models
    # DCF 仍正常
    assert result.dcf_base is not None


def test_calculator_consistency_none_when_all_skip() -> None:
    """所有 active model 全 skip → consistency = None"""
    from app.agents.valuation_calculator import calculate_valuations

    inputs = _maotai_inputs()
    inputs.eps = -5.0
    inputs.free_cash_flow_base = -10e8  # DCF skip
    result = calculate_valuations(inputs, router_override=None)

    assert result.pe_value is None
    assert result.dcf_base is None
    assert result.valuation_consistency is None
