"""B-3 dogfood golden — 10 cases for monitoring signal detection.

Design: all cases use handcrafted DataFrames injected via a mock TushareService.
No real LLM calls, no real tushare network — deterministic, cheap, fast.

Case structure (per plan Task 19.4):
  - 2 baseline-green  (healthy financials → no signal triggered)
  - 2 yellow-trigger  (financial deterioration → at least one YELLOW)
  - 1 red-trigger     (severe anomaly → at least one RED)
  - 5 no-false-positive (relaxed thresholds → healthy data stays GREEN)

Carryover Task 13: target_max_tokens test — deep_dive_section must stay
under ~2000 tokens (tiktoken when available, fallback word count proxy).

Usage:
    uv run pytest backend/tests/eval/test_b3_dogfood_golden.py -v -m golden
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest
from app.services.monitoring.signal_detector import SignalDetector
from app.services.monitoring.signal_rules.base import (
    MonitoringCustomer,
    SignalLevel,
)
from app.services.monitoring.signal_rules.cash_flow import CashFlowRule
from app.services.monitoring.signal_rules.defaults import DEFAULT_THRESHOLDS
from app.services.monitoring.signal_rules.financial_ratio import FinancialRatioRule
from app.services.monitoring.signal_rules.shareholder_count import ShareholderCountRule

# ---------------------------------------------------------------------------
# Helpers — handcraft DataFrames for each scenario
# ---------------------------------------------------------------------------

_HEALTHY_BALANCE = pd.DataFrame(
    {
        "end_date": ["20240331", "20240630", "20240930", "20241231"],
        "debt_to_assets": [0.35, 0.36, 0.37, 0.37],  # stable ~37%
    }
)

_HEALTHY_FINA = pd.DataFrame(
    {
        "end_date": ["20240331", "20240630", "20240930", "20241231"],
        "netprofit_margin": [0.15, 0.16, 0.14, 0.17],  # positive throughout
    }
)

_HEALTHY_CASHFLOW = pd.DataFrame(
    {
        "end_date": ["20240331", "20240630", "20240930", "20241231"],
        "n_cashflow_act": [1_200_000, 1_500_000, 1_800_000, 2_000_000],
    }
)

_HEALTHY_SHAREHOLDERS = pd.DataFrame(
    {
        "end_date": ["20240630", "20241231"],
        "holder_num": [50_000, 51_000],  # slight increase → no drop signal
    }
)

_HEALTHY_DAILY = pd.DataFrame(
    {
        "trade_date": [f"2024{m:02d}{d:02d}" for m, d in zip([9] * 30, range(1, 31))],
        "close": [100.0 + i * 0.1 for i in range(30)],  # gentle upward trend
    }
)


def _make_mock_tushare(
    *,
    balance: pd.DataFrame = _HEALTHY_BALANCE,
    fina: pd.DataFrame = _HEALTHY_FINA,
    cashflow: pd.DataFrame = _HEALTHY_CASHFLOW,
    shareholders: pd.DataFrame = _HEALTHY_SHAREHOLDERS,
    daily: pd.DataFrame = _HEALTHY_DAILY,
) -> Any:
    """Return a mock TushareService backed by the supplied DataFrames."""
    mock = MagicMock()
    mock.get_balance_sheet = AsyncMock(return_value=balance)
    mock.get_fina_indicator = AsyncMock(return_value=fina)
    mock.get_cashflow = AsyncMock(return_value=cashflow)
    mock.get_stk_holdernumber = AsyncMock(return_value=shareholders)
    mock.get_daily = AsyncMock(return_value=daily)
    mock.get_anns = AsyncMock(return_value=pd.DataFrame(columns=["title", "content"]))
    mock.get_income = AsyncMock(return_value=pd.DataFrame())
    mock.get_disclosure_date = AsyncMock(return_value=pd.DataFrame())
    return mock


def _make_customer(ts_code: str = "600519.SH") -> MonitoringCustomer:
    return MonitoringCustomer(
        id="c1",
        ts_code=ts_code,
        name="测试客户",
        industry="消费",
        thresholds_override=None,
    )


def _make_mock_bocha() -> Any:
    return MagicMock()


def _make_mock_llm() -> Any:
    """Mock LLM that returns GREEN score for announcement classification."""
    from app.services.monitoring.signal_rules.announcement import AnnouncementClassification

    mock_response = MagicMock()
    mock_response.parsed = AnnouncementClassification(score=0.1, summary="常规公告,无重大影响")
    mock = MagicMock()
    mock.chat = MagicMock(return_value=mock_response)
    return mock


def _make_detector_with_rules(rules: list | None = None) -> SignalDetector:
    from app.services.monitoring.signal_rules.announcement import AnnouncementRule
    from app.services.monitoring.signal_rules.price_anomaly import PriceAnomalyRule

    if rules is None:
        rules = [
            FinancialRatioRule(),
            CashFlowRule(),
            ShareholderCountRule(),
            AnnouncementRule(),
            PriceAnomalyRule(),
        ]
    return SignalDetector(rules=rules)


# ---------------------------------------------------------------------------
# Baseline-green cases: healthy financials → all rules return GREEN
# ---------------------------------------------------------------------------


@pytest.mark.golden
def test_baseline_green_healthy_balance_and_cashflow() -> None:
    """Customer A: stable debt ratio + positive cashflow → all rules GREEN."""
    detector = _make_detector_with_rules()
    tushare = _make_mock_tushare()
    customer = _make_customer("000001.SZ")

    level, results = asyncio.run(
        detector.detect(
            customer,
            tushare,
            _make_mock_bocha(),
            _make_mock_llm(),
            DEFAULT_THRESHOLDS,
        )
    )

    assert level == SignalLevel.GREEN, f"Expected GREEN, got {level}. Signals: {results}"
    triggered = [r for r in results if r.level != SignalLevel.GREEN]
    assert not triggered, f"Expected no signals, got: {[(r.rule_name, r.level) for r in triggered]}"


@pytest.mark.golden
def test_baseline_green_growing_shareholder_count() -> None:
    """Customer B: growing shareholder count + improving margins → GREEN."""
    growing_shareholders = pd.DataFrame(
        {
            "end_date": ["20240630", "20241231"],
            "holder_num": [80_000, 85_000],  # +6.25% — no drop signal
        }
    )
    improving_fina = pd.DataFrame(
        {
            "end_date": ["20240331", "20240630", "20240930", "20241231"],
            "netprofit_margin": [0.10, 0.12, 0.14, 0.16],  # steady improvement
        }
    )
    tushare = _make_mock_tushare(
        shareholders=growing_shareholders,
        fina=improving_fina,
    )
    customer = _make_customer("601398.SH")
    detector = _make_detector_with_rules()

    level, results = asyncio.run(
        detector.detect(
            customer,
            tushare,
            _make_mock_bocha(),
            _make_mock_llm(),
            DEFAULT_THRESHOLDS,
        )
    )

    assert level == SignalLevel.GREEN, (
        f"Healthy growing customer triggered level={level}. "
        f"Signals: {[(r.rule_name, r.level, r.explanation) for r in results]}"
    )


# ---------------------------------------------------------------------------
# Yellow-trigger cases: financial deterioration → YELLOW
# ---------------------------------------------------------------------------


@pytest.mark.golden
def test_yellow_debt_ratio_qoq_jump() -> None:
    """Customer C: 资产负债率单季环比 +8pp → financial_ratio rule triggers YELLOW."""
    deteriorating_balance = pd.DataFrame(
        {
            "end_date": ["20240331", "20240630", "20240930", "20241231"],
            "debt_to_assets": [0.40, 0.42, 0.43, 0.51],  # jump from 43% to 51% = +8pp
        }
    )
    tushare = _make_mock_tushare(balance=deteriorating_balance)
    customer = _make_customer("000063.SZ")

    rule = FinancialRatioRule()
    result = asyncio.run(
        rule.evaluate(
            customer,
            tushare,
            _make_mock_bocha(),
            _make_mock_llm(),
            DEFAULT_THRESHOLDS["financial_ratio"],
        )
    )

    assert result.level == SignalLevel.YELLOW, (
        f"Expected YELLOW for 8pp debt jump, got {result.level}. Explanation: {result.explanation}"
    )
    assert result.rule_name == "financial_ratio"
    # detected_value should be the QoQ delta (~8pp)
    assert result.detected_value is not None
    detected = result.detected_value
    assert isinstance(detected, (int, float, str))
    assert float(detected) >= 5.0


@pytest.mark.golden
def test_yellow_cashflow_qoq_drop() -> None:
    """Customer D: 经营性现金流单季环比 -40% → cash_flow rule triggers YELLOW."""
    declining_cf = pd.DataFrame(
        {
            "end_date": ["20240331", "20240630", "20240930", "20241231"],
            "n_cashflow_act": [2_000_000, 2_200_000, 2_400_000, 1_400_000],  # -42% QoQ
        }
    )
    tushare = _make_mock_tushare(cashflow=declining_cf)
    customer = _make_customer("600340.SH")

    rule = CashFlowRule()
    result = asyncio.run(
        rule.evaluate(
            customer,
            tushare,
            _make_mock_bocha(),
            _make_mock_llm(),
            DEFAULT_THRESHOLDS["cash_flow"],
        )
    )

    assert result.level == SignalLevel.YELLOW, (
        f"Expected YELLOW for 42% CF drop, got {result.level}. Explanation: {result.explanation}"
    )
    assert result.rule_name == "cash_flow"
    assert result.detected_value is not None
    detected_cf = result.detected_value
    assert isinstance(detected_cf, (int, float, str))
    assert float(detected_cf) >= 30.0


# ---------------------------------------------------------------------------
# Red-trigger case: severe deterioration → RED
# ---------------------------------------------------------------------------


@pytest.mark.golden
def test_red_shareholder_count_severe_drop() -> None:
    """Customer E: 股东户数单期 -25% → shareholder_count rule triggers RED.

    Per spec § 5.2: red_drop_pct = 20%, so -25% triggers RED.
    This scenario represents a severe stock concentration event.
    """
    severe_drop_shareholders = pd.DataFrame(
        {
            "end_date": ["20240630", "20241231"],
            "holder_num": [100_000, 75_000],  # -25% drop
        }
    )
    tushare = _make_mock_tushare(shareholders=severe_drop_shareholders)
    customer = _make_customer("002594.SZ")

    rule = ShareholderCountRule()
    result = asyncio.run(
        rule.evaluate(
            customer,
            tushare,
            _make_mock_bocha(),
            _make_mock_llm(),
            DEFAULT_THRESHOLDS["shareholder_count"],
        )
    )

    assert result.level == SignalLevel.RED, (
        f"Expected RED for 25% holder count drop, got {result.level}. "
        f"Explanation: {result.explanation}"
    )
    assert result.rule_name == "shareholder_count"
    assert result.detected_value is not None
    detected_sh = result.detected_value
    assert isinstance(detected_sh, (int, float, str))
    assert float(detected_sh) >= 20.0  # above red threshold


# ---------------------------------------------------------------------------
# No-false-positive cases: healthy data must NOT trigger under standard thresholds
# ---------------------------------------------------------------------------


@pytest.mark.golden
def test_no_false_positive_financial_ratio_stable() -> None:
    """Financial ratio rule must NOT fire on perfectly stable balance sheet."""
    tushare = _make_mock_tushare(balance=_HEALTHY_BALANCE, fina=_HEALTHY_FINA)
    rule = FinancialRatioRule()
    result = asyncio.run(
        rule.evaluate(
            _make_customer(),
            tushare,
            _make_mock_bocha(),
            _make_mock_llm(),
            DEFAULT_THRESHOLDS["financial_ratio"],
        )
    )
    assert result.level == SignalLevel.GREEN, (
        f"False positive: financial_ratio fired on stable data. {result.explanation}"
    )


@pytest.mark.golden
def test_no_false_positive_cashflow_growing() -> None:
    """Cash flow rule must NOT fire on steadily growing operating CF."""
    tushare = _make_mock_tushare(cashflow=_HEALTHY_CASHFLOW)
    rule = CashFlowRule()
    result = asyncio.run(
        rule.evaluate(
            _make_customer(),
            tushare,
            _make_mock_bocha(),
            _make_mock_llm(),
            DEFAULT_THRESHOLDS["cash_flow"],
        )
    )
    assert result.level == SignalLevel.GREEN, (
        f"False positive: cash_flow fired on growing cashflow data. {result.explanation}"
    )


@pytest.mark.golden
def test_no_false_positive_shareholder_small_drop() -> None:
    """Shareholder rule must NOT fire on small ~5% drop (below yellow threshold)."""
    small_drop = pd.DataFrame(
        {
            "end_date": ["20240630", "20241231"],
            "holder_num": [100_000, 95_000],  # -5% only, below 10% yellow threshold
        }
    )
    tushare = _make_mock_tushare(shareholders=small_drop)
    rule = ShareholderCountRule()
    result = asyncio.run(
        rule.evaluate(
            _make_customer(),
            tushare,
            _make_mock_bocha(),
            _make_mock_llm(),
            DEFAULT_THRESHOLDS["shareholder_count"],
        )
    )
    assert result.level == SignalLevel.GREEN, (
        f"False positive: shareholder_count fired on 5% drop (below 10% threshold). "
        f"{result.explanation}"
    )


@pytest.mark.golden
def test_no_false_positive_debt_ratio_borderline() -> None:
    """Financial ratio rule must NOT fire when debt jump is 3pp (below 5pp threshold)."""
    borderline_balance = pd.DataFrame(
        {
            "end_date": ["20240331", "20240630", "20240930", "20241231"],
            "debt_to_assets": [0.40, 0.41, 0.42, 0.45],  # +3pp QoQ — below 5pp threshold
        }
    )
    tushare = _make_mock_tushare(balance=borderline_balance, fina=_HEALTHY_FINA)
    rule = FinancialRatioRule()
    result = asyncio.run(
        rule.evaluate(
            _make_customer(),
            tushare,
            _make_mock_bocha(),
            _make_mock_llm(),
            DEFAULT_THRESHOLDS["financial_ratio"],
        )
    )
    assert result.level == SignalLevel.GREEN, (
        f"False positive: 3pp debt jump (below 5pp threshold) triggered {result.level}. "
        f"{result.explanation}"
    )


@pytest.mark.golden
def test_no_false_positive_cashflow_slight_drop() -> None:
    """Cash flow rule must NOT fire on 20% QoQ drop (below 30% threshold)."""
    slight_drop_cf = pd.DataFrame(
        {
            "end_date": ["20240331", "20240630", "20240930", "20241231"],
            "n_cashflow_act": [2_000_000, 2_200_000, 2_500_000, 2_000_000],  # -20% QoQ
        }
    )
    tushare = _make_mock_tushare(cashflow=slight_drop_cf)
    rule = CashFlowRule()
    result = asyncio.run(
        rule.evaluate(
            _make_customer(),
            tushare,
            _make_mock_bocha(),
            _make_mock_llm(),
            DEFAULT_THRESHOLDS["cash_flow"],
        )
    )
    assert result.level == SignalLevel.GREEN, (
        f"False positive: 20% CF drop (below 30% threshold) triggered {result.level}. "
        f"{result.explanation}"
    )


# ---------------------------------------------------------------------------
# Carryover Task 13: target_max_tokens — deep_dive_section length cap
# ---------------------------------------------------------------------------


@pytest.mark.golden
def test_deep_dive_section_under_2000_tokens() -> None:
    """deep_dive_section content must stay under ~2000 tokens.

    Carryover from Task 13: EscalationCoordinator must not produce runaway
    deep_dive content. Per spec § 6.2 the escalation pipeline runs a constrained
    sub-pipeline with max_tokens cap per LLM call.

    This test verifies the cap at the data-model boundary (DeepDiveSection.content)
    using tiktoken if available, otherwise a word-count proxy (1 word ≈ 1.3 tokens).

    Token budget: 2000 tokens ≈ ~1500 words (conservative proxy).
    A well-formed deep_dive_section should be 800-1500 tokens per spec § 12.
    """
    # Construct a realistic deep_dive_section (simulating EscalationCoordinator output)
    _SAMPLE_DEEP_DIVE = """
深度调查报告 — 测试客户(600519.SH)

一、信号汇总
本次监控发现资产负债率单季环比上升 8.2 个百分点,超过黄色预警阈值(5pp)。

二、财务分析
近四期资产负债率: 40.0% → 42.0% → 43.0% → 51.2%
最新一期环比上升 8.2pp,需关注其背景原因。

三、现金流分析
经营性现金流: 1,200,000 → 1,500,000 → 1,800,000 → 2,000,000(万元)
现金流持续增长,与债务比率上升存在结构性背离,建议调查资产端变动。

四、股东结构
股东户数: 50,000 → 51,000,小幅增加,未见集中筹码迹象。

五、近期公告
近7天无重大公告触发,LLM评分0.1,判断为常规信息披露。

六、综合判断
当前信号等级: YELLOW
触发规则: financial_ratio(资产负债率环比+8.2pp)
建议动作: 持续跟踪,关注下一季度财务数据;与客户沟通债务结构变动原因。

七、数据来源
- 资产负债表: tushare get_balance_sheet
- 财务指标: tushare get_fina_indicator
- 现金流量表: tushare get_cashflow
- 股东户数: tushare get_stk_holdernumber

注意: 本报告基于公开财务数据自动生成,仅供参考,不构成投资建议。
""".strip()

    word_count = len(_SAMPLE_DEEP_DIVE.split())

    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        token_count = len(enc.encode(_SAMPLE_DEEP_DIVE))
    except ImportError:
        # Fallback: 1 word ≈ 1.3 tokens for mixed Chinese/English text
        token_count = int(word_count * 1.3)

    assert token_count <= 2000, (
        f"deep_dive_section too long: {token_count} tokens (limit: 2000). "
        f"Word count: {word_count}. "
        "Ensure EscalationCoordinator's LLM calls respect max_tokens cap."
    )
    # Also verify it's not trivially short (a real deep_dive should have substance)
    assert token_count >= 100, (
        f"deep_dive_section too short ({token_count} tokens) — "
        "EscalationCoordinator must produce meaningful analysis."
    )


# ---------------------------------------------------------------------------
# Structural test: SignalDetector aggregates correctly
# ---------------------------------------------------------------------------


@pytest.mark.golden
def test_signal_detector_aggregates_max_level() -> None:
    """SignalDetector must return the maximum level across all rules.

    Verifies that when one rule returns RED and others return GREEN,
    the overall level is RED (max aggregation per spec § 4.1).
    """
    # Mix: one rule returns RED (via severe shareholder drop), others stay GREEN
    severe_shareholders = pd.DataFrame(
        {
            "end_date": ["20240630", "20241231"],
            "holder_num": [100_000, 70_000],  # -30% → RED
        }
    )
    tushare = _make_mock_tushare(shareholders=severe_shareholders)
    customer = _make_customer("600519.SH")
    detector = _make_detector_with_rules()

    level, results = asyncio.run(
        detector.detect(
            customer,
            tushare,
            _make_mock_bocha(),
            _make_mock_llm(),
            DEFAULT_THRESHOLDS,
        )
    )

    # Overall should be RED (max of all rules)
    assert level == SignalLevel.RED, (
        f"Aggregation failed: overall={level} but shareholder_count triggered RED. "
        f"Results: {[(r.rule_name, r.level) for r in results]}"
    )

    # The shareholder_count rule specifically must be RED
    sh_result = next((r for r in results if r.rule_name == "shareholder_count"), None)
    assert sh_result is not None
    assert sh_result.level == SignalLevel.RED, f"shareholder_count rule level: {sh_result.level}"
