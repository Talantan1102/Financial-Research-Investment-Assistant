"""M3 RiskPairingMetric — summarization LLM judge.

L0 unit: fake judge 验算法逻辑。
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from eval.dd_report.metrics.base import CaseMeta, MetricInputs
from eval.dd_report.metrics.risk_pairing_metric import (
    RiskPairingMetric,
)


class _AlwaysValidJudge:
    def is_valid_mitigation(self, risk_title: str, risk_desc: str, mitigations: list[str]) -> bool:
        return True


class _AlwaysInvalidJudge:
    def is_valid_mitigation(self, risk_title: str, risk_desc: str, mitigations: list[str]) -> bool:
        return False


def _make_inputs(report: dict[str, Any]) -> MetricInputs:
    return MetricInputs(
        report=report,
        case_meta=CaseMeta("bt-test", "600519.SH", "茅台", date(2024, 6, 30)),
        ground_truth=None,
        tushare_adapter=None,
        kb_lookup=None,
        evaluator_clients={},
    )


def test_all_paired_with_valid_mitigation_gives_score_1() -> None:
    report = {
        "risk_assessment": {
            "market_risk": [
                {
                    "title": "波动",
                    "description": "高 beta",
                    "severity": "medium",
                    "mitigations": ["分批建仓"],
                }
            ],
            "growth_risk": [],
            "event_risk": [],
            "valuation_risk": [],
        },
    }
    m = RiskPairingMetric(judge=_AlwaysValidJudge())
    r = m.compute(_make_inputs(report))
    assert r.value == 1.0
    assert r.details["total"] == 1
    assert r.details["valid"] == 1


def test_unpaired_risk_counts_as_unpaired() -> None:
    report = {
        "risk_assessment": {
            "market_risk": [
                {"title": "波动", "description": "高 beta", "severity": "medium", "mitigations": []}
            ],  # 无 mitigation
            "growth_risk": [],
            "event_risk": [],
            "valuation_risk": [],
        },
    }
    m = RiskPairingMetric(judge=_AlwaysValidJudge())
    r = m.compute(_make_inputs(report))
    assert r.details["total"] == 1
    assert r.details["unpaired"] == 1
    assert r.value == 0.0


def test_paired_but_invalid_judge_counts_as_invalid() -> None:
    report = {
        "risk_assessment": {
            "market_risk": [
                {
                    "title": "波动",
                    "description": "高 beta",
                    "severity": "medium",
                    "mitigations": ["啥也不干"],
                }
            ],
            "growth_risk": [],
            "event_risk": [],
            "valuation_risk": [],
        },
    }
    m = RiskPairingMetric(judge=_AlwaysInvalidJudge())
    r = m.compute(_make_inputs(report))
    assert r.details["paired"] == 1
    assert r.details["valid"] == 0
    assert r.value == 0.0


def test_aggregate_across_4_risk_buckets() -> None:
    report = {
        "risk_assessment": {
            "market_risk": [
                {"title": "X1", "description": "", "severity": "low", "mitigations": ["A"]}
            ],
            "growth_risk": [
                {"title": "X2", "description": "", "severity": "low", "mitigations": []}
            ],
            "event_risk": [
                {"title": "X3", "description": "", "severity": "low", "mitigations": ["B"]}
            ],
            "valuation_risk": [
                {"title": "X4", "description": "", "severity": "low", "mitigations": []}
            ],
        },
    }
    m = RiskPairingMetric(judge=_AlwaysValidJudge())
    r = m.compute(_make_inputs(report))
    # 4 risks total, 2 paired with valid mitigation -> 2/4 = 0.5
    assert r.details["total"] == 4
    assert r.details["paired"] == 2
    assert r.details["valid"] == 2
    assert r.value == 0.5


def test_no_risks_returns_vacuous_one() -> None:
    report: dict[str, Any] = {
        "risk_assessment": {
            "market_risk": [],
            "growth_risk": [],
            "event_risk": [],
            "valuation_risk": [],
        },
    }
    m = RiskPairingMetric(judge=_AlwaysValidJudge())
    r = m.compute(_make_inputs(report))
    assert r.details["total"] == 0
    assert r.value == 1.0


import os
from pathlib import Path

import vcr
from eval.dd_report.metrics.risk_pairing_metric import _EvaluatorPairingJudge

CASSETTE_DIR = Path(__file__).parent / "cassettes"


@pytest.mark.skipif(
    not os.environ.get("OPENROUTER_API_KEY"),
    reason="OPENROUTER_API_KEY not set; L1 cassette test skipped",
)
def test_l1_risk_pairing_judge_via_cassette() -> None:
    from eval.dd_report.llm_swapper import LLMSwapper

    swapper = LLMSwapper()
    client = swapper.get_client("gpt-4o-2024-05-13")
    judge = _EvaluatorPairingJudge(client)
    CASSETTE_DIR.mkdir(parents=True, exist_ok=True)
    with vcr.use_cassette(
        str(CASSETTE_DIR / "risk_pairing_judge.yaml"),
        record_mode="new_episodes",
        match_on=["method", "scheme", "host", "port", "path"],
    ):
        ok = judge.is_valid_mitigation(
            "股价波动风险",
            "茅台 beta=1.2 中期可能 20% 回撤",
            ["分批建仓, 单次仓位不超过总仓 5%", "设 5% 止损线"],
        )
    assert isinstance(ok, bool)
