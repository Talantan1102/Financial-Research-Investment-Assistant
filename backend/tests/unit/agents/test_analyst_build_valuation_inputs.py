"""L0 — Analyst._build_valuation_inputs_from_state real wire from tool_results.

v1.x A5a follow-up #1: 真接通 tushare tool_results → ValuationInputs。

Coverage:
- 完整 tool_results → ValuationInputs 全填 (industry / eps / bvps / shares)
- 缺核心 tool (get_financials / balance_sheet / quote / daily_basic) → None
- 行业关键字 substring match (白酒 / 半导体 / 银行 / 不命中→_default)
- pe ≤ 0 (亏损) → None (eps reverse derive 失败)
- pb ≤ 0 → None
- pe_history 缺 → industry_pe fallback to daily_basic.pe 自身
- cashflow 缺 → free_cash_flow_base = 0 (DCF skip, 不阻塞 PE/PB)
- ToolResult.success=False / error 字段在 output → skip 该 tool
- forecast_growth / company_beta 从 state 透传 (None when 未 wire)
"""

from __future__ import annotations

from typing import Any

import pytest
from app.agents.analyst import Analyst, _index_tool_results, _safe_float
from app.agents.schemas import ResearchState, ToolResult
from app.agents.valuation_calculator import ValuationInputs
from app.services.llm_service import LLMService


class _FakeLLM(LLMService):
    """Minimal LLMService stub — Analyst._build_valuation_inputs_from_state
    不调 LLM,只需 Analyst 构造时拿一个 LLMService 对象。"""

    def __init__(self) -> None:
        pass  # skip parent init — 测试只 touch _build_valuation_inputs_from_state


def _make_analyst() -> Analyst:
    a = object.__new__(Analyst)
    a._llm = _FakeLLM()
    return a


def _make_state(
    *,
    tool_results: list[ToolResult],
    user_message: str = "尽调 600519.SH 贵州茅台 白酒",
    target_entity: str | None = "贵州茅台",
    forecast_growth: float | None = None,
) -> ResearchState:
    return ResearchState(
        user_id="u",
        session_id="s",
        user_message=user_message,
        request_id="r",
        target_entity=target_entity,
        tool_results=tool_results,
        forecast_growth=forecast_growth,
    )


def _tr(name: str, output: dict[str, Any], *, success: bool = True) -> ToolResult:
    return ToolResult(
        tool_name=name,
        args={"ts_code": "600519.SH"},
        success=success,
        output=output if success else None,
        error=None if success else "boom",
        latency_ms=10,
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_complete_tool_results_yields_valuation_inputs() -> None:
    """完整 tool_results → ValuationInputs 18 字段全填,industry 命中白酒。"""
    tool_results = [
        _tr("get_stock_quote", {"price": 1800.0, "change_pct": 1.0, "volume": 1000.0}),
        _tr(
            "get_daily_basic",
            {
                "ts_code": "600519.SH",
                "pe": 25.0,
                "pb": 8.0,
                "ps": 8.0,
                "dv_ratio": 1.2,
                "total_mv": 22000000.0,  # 万元
                "circ_mv": 22000000.0,
                "turnover_rate": 0.5,
            },
        ),
        _tr(
            "get_financials",
            {
                "ts_code": "600519.SH",
                "period": "latest",
                "revenue": 1000000000.0,
                "net_profit": 500000000.0,
                "roe": 30.0,
                "pe": 25.0,
            },
        ),
        _tr(
            "get_balance_sheet",
            {
                "ts_code": "600519.SH",
                "total_assets": 100000000.0,
                "total_liab": 20000000.0,
                "total_cur_assets": 50000000.0,
                "total_cur_liab": 15000000.0,
                "asset_liability_ratio": 0.2,
                "current_ratio": 3.3,
            },
        ),
        _tr(
            "get_cashflow",
            {
                "ts_code": "600519.SH",
                "n_cashflow_act": 300000000.0,
                "n_cashflow_inv_act": -50000000.0,
                "n_cash_flows_fnc_act": -10000000.0,
                "positive_ocf": True,
            },
        ),
        _tr(
            "get_pe_history",
            {
                "ts_code": "600519.SH",
                "current_pe": 25.0,
                "historical_percentile": 0.4,
                "min_pe": 15.0,
                "max_pe": 50.0,
                "median_pe": 28.0,
                "valuation_band": "合理",
            },
        ),
    ]
    state = _make_state(tool_results=tool_results, forecast_growth=0.10)

    analyst = _make_analyst()
    inputs = analyst._build_valuation_inputs_from_state(state)

    assert inputs is not None
    assert isinstance(inputs, ValuationInputs)
    # industry: '白酒' 命中
    assert inputs.industry_classification == "白酒"
    # eps = price / pe = 1800 / 25 = 72
    assert inputs.eps == pytest.approx(72.0, rel=1e-3)
    # bvps = price / pb = 1800 / 8 = 225
    assert inputs.book_value_per_share == pytest.approx(225.0, rel=1e-3)
    # shares = (total_mv / price) × 10000 = (22000000 / 1800) × 10000 = 122222222.2
    assert inputs.shares_outstanding == pytest.approx(22000000.0 / 1800.0 * 10000.0, rel=1e-3)
    # industry_pe_median = pe_history.median_pe = 28
    assert inputs.industry_pe_median == pytest.approx(28.0, rel=1e-3)
    # debt_to_equity = liab / equity = 20m / 80m = 0.25
    assert inputs.debt_to_equity == pytest.approx(0.25, rel=1e-3)
    # net_debt = total_liab approx (cash 不暴露)
    assert inputs.net_debt == pytest.approx(20000000.0, rel=1e-3)
    # free_cash_flow_base = n_cashflow_act = 300m
    assert inputs.free_cash_flow_base == pytest.approx(300000000.0, rel=1e-3)
    # forecast_growth passthrough from state
    assert inputs.forecast_growth == pytest.approx(0.10, rel=1e-3)
    # company_beta: 未 wire → None
    assert inputs.company_beta is None
    # industry DCF defaults: 白酒 → wacc=0.07, terminal=0.025
    assert inputs.industry_baseline_wacc == pytest.approx(0.07, rel=1e-3)
    assert inputs.industry_terminal_growth == pytest.approx(0.025, rel=1e-3)
    # EBITDA 信号缺 → 0 (EV-EBITDA model 自然 skip)
    assert inputs.ebitda == 0.0


# ---------------------------------------------------------------------------
# Missing core tool → None
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "missing_tool",
    [
        "get_stock_quote",
        "get_daily_basic",
        "get_financials",
        "get_balance_sheet",
    ],
)
def test_missing_core_tool_returns_none(missing_tool: str) -> None:
    """缺任一核心 tool → return None (graceful skip)."""
    all_tools = {
        "get_stock_quote": _tr(
            "get_stock_quote", {"price": 1800.0, "change_pct": 1.0, "volume": 100.0}
        ),
        "get_daily_basic": _tr(
            "get_daily_basic",
            {"pe": 25.0, "pb": 8.0, "total_mv": 22000000.0},
        ),
        "get_financials": _tr(
            "get_financials",
            {"revenue": 1.0e9, "net_profit": 5.0e8, "roe": 30.0, "pe": 25.0},
        ),
        "get_balance_sheet": _tr(
            "get_balance_sheet",
            {
                "total_assets": 1.0e8,
                "total_liab": 2.0e7,
                "total_cur_assets": 5.0e7,
                "total_cur_liab": 1.5e7,
            },
        ),
    }
    tool_results = [tr for name, tr in all_tools.items() if name != missing_tool]
    state = _make_state(tool_results=tool_results)

    analyst = _make_analyst()
    inputs = analyst._build_valuation_inputs_from_state(state)

    assert inputs is None


def test_unsuccessful_tool_result_treated_as_missing() -> None:
    """tool_result.success=False 应跟缺 tool 等价 (output=None,_index_tool_results 过滤)。"""
    tool_results = [
        _tr("get_stock_quote", {}, success=False),
        _tr(
            "get_daily_basic",
            {"pe": 25.0, "pb": 8.0, "total_mv": 22000000.0},
        ),
        _tr(
            "get_financials",
            {"revenue": 1.0e9, "net_profit": 5.0e8, "roe": 30.0, "pe": 25.0},
        ),
        _tr(
            "get_balance_sheet",
            {
                "total_assets": 1.0e8,
                "total_liab": 2.0e7,
                "total_cur_assets": 5.0e7,
                "total_cur_liab": 1.5e7,
            },
        ),
    ]
    state = _make_state(tool_results=tool_results)

    analyst = _make_analyst()
    inputs = analyst._build_valuation_inputs_from_state(state)

    assert inputs is None


def test_tool_output_with_error_field_skipped() -> None:
    """ToolResult.output 含 'error' (tool 内部 no-data fallback) → 视为缺数据。"""
    tool_results = [
        _tr("get_stock_quote", {"price": 1800.0, "change_pct": 1.0, "volume": 100.0}),
        _tr(
            "get_daily_basic",
            {"ts_code": "X", "error": "no data"},  # tool 自身返 no-data fallback
        ),
        _tr(
            "get_financials",
            {"revenue": 1.0e9, "net_profit": 5.0e8, "roe": 30.0, "pe": 25.0},
        ),
        _tr(
            "get_balance_sheet",
            {
                "total_assets": 1.0e8,
                "total_liab": 2.0e7,
                "total_cur_assets": 5.0e7,
                "total_cur_liab": 1.5e7,
            },
        ),
    ]
    state = _make_state(tool_results=tool_results)

    analyst = _make_analyst()
    inputs = analyst._build_valuation_inputs_from_state(state)

    assert inputs is None  # daily_basic error → 核心缺


# ---------------------------------------------------------------------------
# Invalid PE / PB / price → None
# ---------------------------------------------------------------------------


def test_invalid_pe_zero_returns_none() -> None:
    """pe ≤ 0 (亏损 / 数据 corrupt) → 无法反推 eps → None."""
    tool_results = [
        _tr("get_stock_quote", {"price": 1800.0, "change_pct": 1.0, "volume": 100.0}),
        _tr(
            "get_daily_basic",
            {"pe": 0.0, "pb": 8.0, "total_mv": 22000000.0},  # pe = 0
        ),
        _tr(
            "get_financials",
            {"revenue": 1.0e9, "net_profit": 0.0, "roe": 0.0, "pe": 0.0},
        ),
        _tr(
            "get_balance_sheet",
            {
                "total_assets": 1.0e8,
                "total_liab": 2.0e7,
                "total_cur_assets": 5.0e7,
                "total_cur_liab": 1.5e7,
            },
        ),
    ]
    state = _make_state(tool_results=tool_results)

    analyst = _make_analyst()
    inputs = analyst._build_valuation_inputs_from_state(state)

    assert inputs is None


def test_invalid_pb_returns_none() -> None:
    """pb ≤ 0 (负净资产) → None."""
    tool_results = [
        _tr("get_stock_quote", {"price": 1800.0, "change_pct": 1.0, "volume": 100.0}),
        _tr(
            "get_daily_basic",
            {"pe": 25.0, "pb": -1.0, "total_mv": 22000000.0},  # pb < 0
        ),
        _tr(
            "get_financials",
            {"revenue": 1.0e9, "net_profit": 5.0e8, "roe": 30.0, "pe": 25.0},
        ),
        _tr(
            "get_balance_sheet",
            {
                "total_assets": 1.0e8,
                "total_liab": 2.0e7,
                "total_cur_assets": 5.0e7,
                "total_cur_liab": 1.5e7,
            },
        ),
    ]
    state = _make_state(tool_results=tool_results)

    analyst = _make_analyst()
    inputs = analyst._build_valuation_inputs_from_state(state)

    assert inputs is None


# ---------------------------------------------------------------------------
# Optional tools
# ---------------------------------------------------------------------------


def test_missing_pe_history_falls_back_to_daily_basic_pe() -> None:
    """缺 get_pe_history → industry_pe_avg/median 用 daily_basic.pe 自身 (单点 fallback)."""
    tool_results = [
        _tr("get_stock_quote", {"price": 1800.0, "change_pct": 1.0, "volume": 100.0}),
        _tr(
            "get_daily_basic",
            {"pe": 25.0, "pb": 8.0, "total_mv": 22000000.0},
        ),
        _tr(
            "get_financials",
            {"revenue": 1.0e9, "net_profit": 5.0e8, "roe": 30.0, "pe": 25.0},
        ),
        _tr(
            "get_balance_sheet",
            {
                "total_assets": 1.0e8,
                "total_liab": 2.0e7,
                "total_cur_assets": 5.0e7,
                "total_cur_liab": 1.5e7,
            },
        ),
        # 不放 get_pe_history
    ]
    state = _make_state(tool_results=tool_results)

    analyst = _make_analyst()
    inputs = analyst._build_valuation_inputs_from_state(state)

    assert inputs is not None
    # Fallback: industry_pe_avg/median 都用 pe=25 自身
    assert inputs.industry_pe_avg == pytest.approx(25.0)
    assert inputs.industry_pe_median == pytest.approx(25.0)


def test_missing_cashflow_yields_zero_fcf() -> None:
    """缺 get_cashflow → free_cash_flow_base = 0 (DCF 自然 skip; 不阻塞 PE/PB)."""
    tool_results = [
        _tr("get_stock_quote", {"price": 1800.0, "change_pct": 1.0, "volume": 100.0}),
        _tr(
            "get_daily_basic",
            {"pe": 25.0, "pb": 8.0, "total_mv": 22000000.0},
        ),
        _tr(
            "get_financials",
            {"revenue": 1.0e9, "net_profit": 5.0e8, "roe": 30.0, "pe": 25.0},
        ),
        _tr(
            "get_balance_sheet",
            {
                "total_assets": 1.0e8,
                "total_liab": 2.0e7,
                "total_cur_assets": 5.0e7,
                "total_cur_liab": 1.5e7,
            },
        ),
    ]
    state = _make_state(tool_results=tool_results)

    analyst = _make_analyst()
    inputs = analyst._build_valuation_inputs_from_state(state)

    assert inputs is not None
    assert inputs.free_cash_flow_base == 0.0


# ---------------------------------------------------------------------------
# Industry classification heuristic
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "user_message,target_entity,expected",
    [
        ("尽调 600519.SH 贵州茅台 白酒", "贵州茅台", "白酒"),
        ("尽调 半导体龙头 中芯国际", "中芯国际", "半导体"),
        ("尽调 银行股 工商银行", "工商银行", "银行"),
        ("尽调 量子计算 X 公司", "X公司", "_default"),  # 不命中
        ("尽调", None, "_default"),  # 空 hint
    ],
)
def test_industry_classification_substring_match(
    user_message: str, target_entity: str | None, expected: str
) -> None:
    """industry_classification 用 user_message + target_entity 的 substring match."""
    tool_results = [
        _tr("get_stock_quote", {"price": 1800.0, "change_pct": 1.0, "volume": 100.0}),
        _tr(
            "get_daily_basic",
            {"pe": 25.0, "pb": 8.0, "total_mv": 22000000.0},
        ),
        _tr(
            "get_financials",
            {"revenue": 1.0e9, "net_profit": 5.0e8, "roe": 30.0, "pe": 25.0},
        ),
        _tr(
            "get_balance_sheet",
            {
                "total_assets": 1.0e8,
                "total_liab": 2.0e7,
                "total_cur_assets": 5.0e7,
                "total_cur_liab": 1.5e7,
            },
        ),
    ]
    state = _make_state(
        tool_results=tool_results, user_message=user_message, target_entity=target_entity
    )

    analyst = _make_analyst()
    inputs = analyst._build_valuation_inputs_from_state(state)

    assert inputs is not None
    assert inputs.industry_classification == expected


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_index_tool_results_filters_failed_and_error_outputs() -> None:
    """_index_tool_results 过滤 success=False 和 output 含 'error' key 的结果."""
    tr_ok = _tr("get_stock_quote", {"price": 1.0})
    tr_failed = _tr("get_daily_basic", {}, success=False)
    tr_error_payload = ToolResult(
        tool_name="get_financials",
        args={},
        success=True,
        output={"ts_code": "X", "error": "no data"},
        latency_ms=10,
    )

    index = _index_tool_results([tr_ok, tr_failed, tr_error_payload])

    assert "get_stock_quote" in index
    assert "get_daily_basic" not in index
    assert "get_financials" not in index  # error payload filtered


def test_safe_float_edge_cases() -> None:
    """_safe_float defensive coverage: None / missing key / non-numeric / nan."""
    assert _safe_float(None, "x") is None
    assert _safe_float({}, "x") is None
    assert _safe_float({"x": None}, "x") is None
    assert _safe_float({"x": "not a num"}, "x") is None
    assert _safe_float({"x": float("inf")}, "x") is None
    assert _safe_float({"x": float("nan")}, "x") is None
    assert _safe_float({"x": 0}, "x") == 0.0
    assert _safe_float({"x": "1.5"}, "x") == 1.5  # str-coercible OK


# ---------------------------------------------------------------------------
# C7 regression: PB comparable tautology + insolvent firm debt_to_equity
# ---------------------------------------------------------------------------


def test_pb_comparables_are_zero_not_self_referential() -> None:
    """C7 regression: industry_pb_avg/median must be 0.0 (lens skipped),
    not pb*1.0 (self-referential tautology that kills cross-check signal)."""
    tool_results = [
        _tr("get_stock_quote", {"price": 1800.0, "change_pct": 1.0, "volume": 100.0}),
        _tr("get_daily_basic", {"pe": 25.0, "pb": 8.0, "total_mv": 22000000.0}),
        _tr("get_financials", {"revenue": 1.0e9, "net_profit": 5.0e8, "roe": 30.0}),
        _tr(
            "get_balance_sheet",
            {"total_assets": 1.0e8, "total_liab": 2.0e7},
        ),
    ]
    state = _make_state(tool_results=tool_results)
    analyst = _make_analyst()
    inputs = analyst._build_valuation_inputs_from_state(state)

    assert inputs is not None
    # C7: both PB comparables must be 0 so the PB lens skips via
    # InsufficientDataForModelError (same as EV/EBITDA placeholder).
    assert inputs.industry_pb_avg == 0.0, "C7: pb_avg must be 0 (lens skip)"
    assert inputs.industry_pb_median == 0.0, "C7: pb_median must be 0 (lens skip)"


def test_insolvent_firm_gets_inf_debt_to_equity() -> None:
    """C7 regression: total_liab > total_assets (negative equity/insolvent) must
    yield debt_to_equity=float('inf'), so compute_company_wacc raises
    InsufficientDataForModelError and DCF is skipped (not silently lowered WACC)."""
    import math

    tool_results = [
        _tr("get_stock_quote", {"price": 1800.0, "change_pct": 1.0, "volume": 100.0}),
        _tr("get_daily_basic", {"pe": 25.0, "pb": 8.0, "total_mv": 22000000.0}),
        _tr("get_financials", {"revenue": 1.0e9, "net_profit": 5.0e8, "roe": 30.0}),
        _tr(
            "get_balance_sheet",
            {
                "total_assets": 5.0e7,  # assets < liab → insolvent
                "total_liab": 1.0e8,  # liab > assets
            },
        ),
    ]
    state = _make_state(tool_results=tool_results)
    analyst = _make_analyst()
    inputs = analyst._build_valuation_inputs_from_state(state)

    assert inputs is not None
    # C7: insolvent company must have infinite d/e, not 0 (which would under-state risk)
    assert not math.isfinite(inputs.debt_to_equity), (
        "C7: insolvent firm (liab > assets) must get debt_to_equity=inf, "
        "not 0.0 (which yields a spuriously low WACC)"
    )
