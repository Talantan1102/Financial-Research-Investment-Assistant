"""M5 CompositeJudgeMetric — multi-LLM consensus.

L0: fake EvaluatorClient, 验 majority / disagreement 逻辑。
L1 cassette: 3 真 LLM 跑共识, 验 prompt 不漂。
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import vcr
from eval.dd_report.metrics.base import CaseMeta, MetricInputs
from eval.dd_report.metrics.composite_judge_metric import CompositeJudgeMetric

CASSETTE_DIR = Path(__file__).parent / "cassettes"


class _FakeClient:
    def __init__(self, score: int, evidence: str = "ok") -> None:
        self._score = score
        self._evidence = evidence

    def chat(self, prompt: str, response_format: Any = None) -> str:
        return f'{{"score": {self._score}, "reasoning": "{self._evidence}"}}'


def _make_inputs(clients: dict) -> MetricInputs:
    return MetricInputs(
        report={
            "target_name": "茅台",
            "target_overview": {"narrative": "茅台是大白马"},
            "investment_recommendation": {
                "recommendation": "recommend_buy",
                "narrative": "看多",
            },
        },
        case_meta=CaseMeta("bt-test", "600519.SH", "茅台", date(2024, 6, 30)),
        ground_truth=None,
        tushare_adapter=None,
        kb_lookup=None,
        evaluator_clients=clients,
    )


def test_3_judges_consensus_mean_majority() -> None:
    clients = {
        "gpt-4o-2024-05-13": _FakeClient(8),
        "qwen2.5-72b-instruct": _FakeClient(7),
        "deepseek-v3": _FakeClient(8),
    }
    m = CompositeJudgeMetric()
    r = m.compute(_make_inputs(clients))
    assert r.details["mean"] == pytest.approx((8 + 7 + 8) / 3)
    # majority = median([8,7,8]) = 8
    assert r.details["majority"] == 8.0
    assert r.details["disagreement_max"] == 1.0


def test_high_disagreement_flags_audit() -> None:
    clients = {
        "gpt-4o-2024-05-13": _FakeClient(9),
        "qwen2.5-72b-instruct": _FakeClient(3),  # 6 分差
        "deepseek-v3": _FakeClient(7),
    }
    m = CompositeJudgeMetric()
    r = m.compute(_make_inputs(clients))
    assert r.details["disagreement_max"] == 6.0
    assert r.details["needs_audit"] is True


def test_consensus_low_quality_flag() -> None:
    clients = {
        "gpt-4o-2024-05-13": _FakeClient(3),
        "qwen2.5-72b-instruct": _FakeClient(4),
        "deepseek-v3": _FakeClient(3),
    }
    m = CompositeJudgeMetric()
    r = m.compute(_make_inputs(clients))
    assert r.details["low_quality"] is True


def test_main_value_is_mean_score() -> None:
    clients = {
        "gpt-4o-2024-05-13": _FakeClient(8),
        "qwen2.5-72b-instruct": _FakeClient(7),
        "deepseek-v3": _FakeClient(7),
    }
    m = CompositeJudgeMetric()
    r = m.compute(_make_inputs(clients))
    assert r.value == pytest.approx((8 + 7 + 7) / 3)


def test_missing_clients_raises() -> None:
    m = CompositeJudgeMetric()
    with pytest.raises(ValueError, match="needs at least 3"):
        m.compute(_make_inputs({"gpt-4o-2024-05-13": _FakeClient(5)}))


def test_malformed_json_score_treated_as_neutral_5() -> None:
    class _MalformedClient:
        def chat(self, prompt: str, response_format: Any = None) -> str:
            return "I cannot evaluate this"

    clients = {
        "gpt-4o-2024-05-13": _MalformedClient(),
        "qwen2.5-72b-instruct": _FakeClient(8),
        "deepseek-v3": _FakeClient(7),
    }
    m = CompositeJudgeMetric()
    r = m.compute(_make_inputs(clients))
    # malformed -> 5 默认 + 8 + 7 = 20/3
    assert r.details["mean"] == pytest.approx(20 / 3)
    assert r.details["parse_failures"] >= 1


@pytest.mark.skipif(
    not os.environ.get("OPENROUTER_API_KEY"),
    reason="OPENROUTER_API_KEY not set; L1 cassette test skipped",
)
def test_l1_composite_judge_3llm_via_cassette() -> None:
    from eval.dd_report.llm_swapper import LLMSwapper

    swapper = LLMSwapper()
    clients = {
        m: swapper.get_client(m)
        for m in (
            "gpt-4o-2024-05-13",
            "qwen2.5-72b-instruct",
            "deepseek-v3",
        )
    }
    inputs = MetricInputs(
        report={
            "target_name": "贵州茅台",
            "target_overview": {"narrative": "茅台是大白马稳健蓝筹, 净利润 +15%."},
            "investment_recommendation": {
                "recommendation": "recommend_buy",
                "narrative": "估值合理,建议买入, 目标价 1700-1900",
            },
        },
        case_meta=CaseMeta("bt-test", "600519.SH", "茅台", date(2024, 6, 30)),
        ground_truth=None,
        tushare_adapter=None,
        kb_lookup=None,
        evaluator_clients=clients,
    )
    m = CompositeJudgeMetric()
    CASSETTE_DIR.mkdir(parents=True, exist_ok=True)
    with vcr.use_cassette(
        str(CASSETTE_DIR / "composite_judge_3llm.yaml"),
        record_mode="new_episodes",
        match_on=["method", "scheme", "host", "port", "path"],
    ):
        r = m.compute(inputs)
    assert r.value is not None
    assert 0 <= r.value <= 10
    assert len(r.details["per_judge"]) == 3
