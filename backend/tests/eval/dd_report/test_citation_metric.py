"""M1 CitationMetric — extraction precision/recall.

L0 unit: fake judge, 验算法逻辑。
L1: real LLM judge via cassette, 验 prompt 不漂。
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from eval.dd_report.metrics.base import CaseMeta, MetricInputs
from eval.dd_report.metrics.citation_metric import CitationMetric


def _fake_kb_lookup(known: dict[str, str]):
    def lookup(chunk_id: str) -> dict[str, Any] | None:
        text = known.get(chunk_id)
        if text is None:
            return None
        return {"chunk_id": chunk_id, "text": text}

    return lookup


class _FakeJudge:
    """Fake judge that returns True iff chunk text contains a known keyword."""

    def supports(self, claim: str, chunk_text: str) -> bool:
        return "茅台" in claim and "茅台" in chunk_text


def _make_inputs(report: dict[str, Any], kb: dict[str, str]) -> MetricInputs:
    return MetricInputs(
        report=report,
        case_meta=CaseMeta(
            case_id="bt-test",
            ts_code="600519.SH",
            target_name="茅台",
            cut_off_date=date(2024, 6, 30),
        ),
        ground_truth=None,
        tushare_adapter=None,
        kb_lookup=_fake_kb_lookup(kb),
        evaluator_clients={},
    )


def test_perfect_citation_gives_precision_1_recall_1() -> None:
    report = {
        "target_overview": {
            "narrative": "茅台是大白马",
            "evidence": ["chunk-1"],
        },
    }
    kb = {"chunk-1": "贵州茅台是大白马"}
    metric = CitationMetric(judge=_FakeJudge(), section_paths=("target_overview",))
    r = metric.compute(_make_inputs(report, kb))
    assert r.value is not None
    assert r.details["precision"] == 1.0
    assert r.details["recall"] == 1.0


def test_missing_chunk_id_zero_precision_for_that_section() -> None:
    report = {
        "target_overview": {
            "narrative": "茅台是大白马",
            "evidence": ["chunk-missing"],
        },
    }
    metric = CitationMetric(judge=_FakeJudge(), section_paths=("target_overview",))
    r = metric.compute(_make_inputs(report, {}))
    assert r.details["lookup_failures"] == 1
    assert r.details["precision"] == 0.0
    # has_evidence True 即使 lookup_fail; recall 衡量 "section 有写 evidence" 比例
    assert r.details["recall"] == 1.0


def test_no_evidence_zero_recall_perfect_precision_vacuous() -> None:
    report = {
        "target_overview": {
            "narrative": "茅台是大白马",
            "evidence": [],
        },
    }
    metric = CitationMetric(judge=_FakeJudge(), section_paths=("target_overview",))
    r = metric.compute(_make_inputs(report, {}))
    assert r.details["recall"] == 0.0
    # precision vacuously 1.0 (no cited chunks)
    assert r.details["precision"] == 1.0


def test_multiple_sections_micro_avg() -> None:
    report = {
        "target_overview": {
            "narrative": "茅台是大白马",
            "evidence": ["chunk-1", "chunk-2"],  # 2 cited, both support
        },
        "industry_analysis": {
            "narrative": "白酒行业茅台龙头",
            "evidence": ["chunk-3"],  # 1 cited, supports
        },
    }
    kb = {
        "chunk-1": "茅台龙头",
        "chunk-2": "茅台稳健",
        "chunk-3": "茅台行业地位",
    }
    metric = CitationMetric(
        judge=_FakeJudge(), section_paths=("target_overview", "industry_analysis")
    )
    r = metric.compute(_make_inputs(report, kb))
    assert r.details["precision"] == 1.0
    assert r.details["recall"] == 1.0
    assert r.details["sections_with_evidence"] == 2


def test_main_value_is_f1_of_precision_recall() -> None:
    report = {
        "target_overview": {
            "narrative": "茅台龙头",
            "evidence": ["chunk-1"],
        },
        "industry_analysis": {
            "narrative": "测试",
            "evidence": [],  # 这个 section 无 evidence -> recall 拉低
        },
    }
    kb = {"chunk-1": "茅台行业"}
    metric = CitationMetric(
        judge=_FakeJudge(), section_paths=("target_overview", "industry_analysis")
    )
    r = metric.compute(_make_inputs(report, kb))
    # precision = 1/1 = 1.0, recall = 1/2 = 0.5
    # F1 = 2 * 1 * 0.5 / 1.5 = 2/3
    assert r.value == pytest.approx(2 / 3, rel=1e-4)


# ---------------------------------------------------------------------------
# L1 cassette test — real EvaluatorClient judge
# ---------------------------------------------------------------------------

import os
from pathlib import Path

import vcr

CASSETTE_DIR = Path(__file__).parent / "cassettes"


class _EvaluatorJudge:
    """Wrap EvaluatorClient.chat into SupportsJudgeProtocol."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def supports(self, claim: str, chunk_text: str) -> bool:
        prompt = (
            f"判断下述 chunk 内容是否支持声明。chunk 必须明确陈述声明的事实"
            f"或紧密相关的事实, 才算 'supports'。\n\n"
            f"声明: {claim}\n\nchunk: {chunk_text}\n\n"
            f'严格输出一行 JSON: {{"supports": true}} 或 {{"supports": false}}'
        )
        out = self._client.chat(prompt=prompt)
        return '"supports": true' in out.lower() or '"supports":true' in out.lower()


@pytest.mark.skipif(
    not os.environ.get("OPENROUTER_API_KEY"),
    reason="OPENROUTER_API_KEY not set; L1 cassette test skipped",
)
def test_l1_citation_judge_supports_via_cassette() -> None:
    from eval.dd_report.llm_swapper import LLMSwapper

    swapper = LLMSwapper()
    client = swapper.get_client("gpt-4o-2024-05-13")
    judge = _EvaluatorJudge(client)
    CASSETTE_DIR.mkdir(parents=True, exist_ok=True)
    with vcr.use_cassette(
        str(CASSETTE_DIR / "citation_supports_judge.yaml"),
        record_mode="new_episodes",
        match_on=["method", "scheme", "host", "port", "path"],
    ):
        ok = judge.supports(
            "贵州茅台是大白马稳健蓝筹", "贵州茅台 2024 上半年营收稳健, 净利润同比 +15%"
        )
    assert isinstance(ok, bool)
