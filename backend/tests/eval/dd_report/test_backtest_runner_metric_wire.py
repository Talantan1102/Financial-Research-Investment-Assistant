"""BacktestRunner Phase 2 wire — MetricRegistry + LeakDetector + 写表."""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from typing import Any
from uuid import uuid4

import pytest
from eval.dd_report.backtest_runner import BacktestCase, BacktestRunner
from eval.dd_report.metrics.base import (
    MetricInputs,
    MetricRegistry,
    MetricResult,
)


class _DummyTushare:
    def income(self, **kwargs: Any) -> list[dict[str, Any]]:
        return [{"ann_date": "20240601", "end_date": "20240331", "revenue": 1.5e10}]

    def daily(self, **kwargs: Any) -> list[dict[str, Any]]:
        return []

    def balancesheet(self, **kwargs: Any) -> list[dict[str, Any]]:
        return []

    def cashflow(self, **kwargs: Any) -> list[dict[str, Any]]:
        return []

    def anns(self, **kwargs: Any) -> list[dict[str, Any]]:
        return []


class _DummyKB:
    def search(self, query: str, k: int = 10, **kw: Any) -> list[Any]:
        return []


class _DummyClient:
    model = "fake"

    def chat(self, prompt: str, response_format: Any = None) -> str:
        return '{"score": 8, "reasoning": "ok"}'


class _DummySwapper:
    def get_client(self, model_id: str) -> Any:
        return _DummyClient()


class _DummyPipeline:
    def run(
        self,
        *,
        target_name: str,
        ts_code: str,
        tushare_adapter: Any,
        kb_adapter: Any,
        evaluator_client: Any,
    ) -> dict[str, Any]:
        return {
            "target_name": target_name,
            "target_close_price_at_gen": 1500.0,
            "target_overview": {"narrative": "测试 narrative", "evidence": []},
            "financial_analysis": {"narrative": "财务分析", "evidence": [], "key_metrics": []},
            "risk_assessment": {
                "market_risk": [],
                "growth_risk": [],
                "event_risk": [],
                "valuation_risk": [],
            },
            "investment_recommendation": {
                "recommendation": "recommend_hold",
                "estimated_target_price_range": {"low": 1400, "high": 1600},
            },
        }


class _ConstMetric:
    def __init__(self, name: str, value: float) -> None:
        self.name = name
        self._value = value

    def compute(self, inputs: MetricInputs) -> MetricResult:
        return MetricResult(name=self.name, value=self._value, details={"k": "v"})


def test_run_one_writes_backtest_runs_and_eval_results(tmp_path) -> None:
    db = tmp_path / "eval.db"
    from app.services.eval_recorder import EvalRecorder

    EvalRecorder(db).init_schema()

    runner = BacktestRunner(
        swapper=_DummySwapper(),  # type: ignore[arg-type]
        tushare_inner=_DummyTushare(),
        kb_inner=_DummyKB(),
        db_path=db,
        pipeline=_DummyPipeline(),
        metric_registry=MetricRegistry(
            [
                _ConstMetric("m1_citation", 0.9),
                _ConstMetric("m2_numerical", 0.85),
                _ConstMetric("m3_risk_pairing", 0.7),
                _ConstMetric("m5_composite", 8.0),
            ]
        ),  # M4 skipped (ground_truth=None)
    )
    case = BacktestCase(
        case_id=f"bt-{uuid4().hex[:8]}",
        ts_code="600519.SH",
        target_name="茅台",
        cut_off_date=date(2024, 6, 30),
    )
    run_id = runner.run_one(
        case=case,
        evaluator_llm="gpt-4o-2024-05-13",
        ablation_variant="V0_baseline",
        git_sha="testsha",
    )

    with sqlite3.connect(db) as con:
        con.row_factory = sqlite3.Row
        r = con.execute("SELECT * FROM backtest_runs WHERE run_id = ?", (run_id,)).fetchone()
    assert r["status"] == "completed"
    assert r["llm_model"] == "gpt-4o-2024-05-13"
    assert r["ablation_variant"] == "V0_baseline"
    metric_summary = json.loads(r["metric_summary_json"])
    assert metric_summary["m1_citation"] == 0.9

    with sqlite3.connect(db) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT * FROM eval_results WHERE backtest_run_id = ?", (run_id,)
        ).fetchall()
    assert len(rows) == 1
    er = rows[0]
    assert er["case_id"] == case.case_id
    assert er["cut_off_date"] == "2024-06-30"
    assert er["evaluator_llm"] == "gpt-4o-2024-05-13"
    mscores = json.loads(er["metric_scores_json"])
    assert mscores["m5_composite_mean"] == 8.0


def test_run_one_leakdetector_completes_when_adapter_blocks_leak(tmp_path) -> None:
    """spec § 4.5: LeakDetector wired into run_one; adapter ann_date filter cleans
    rows before pipeline sees them, so pipeline output has no leak and run completes."""
    db = tmp_path / "eval.db"
    from app.services.eval_recorder import EvalRecorder

    EvalRecorder(db).init_schema()

    class _LeakyTushare:
        def income(self, **kwargs: Any) -> list[dict[str, Any]]:
            return [{"ann_date": "20250715", "end_date": "20250630", "revenue": 1.5e10}]

        def daily(self, **kwargs: Any) -> list[dict[str, Any]]:
            return []

        def balancesheet(self, **kwargs: Any) -> list[dict[str, Any]]:
            return []

        def cashflow(self, **kwargs: Any) -> list[dict[str, Any]]:
            return []

        def anns(self, **kwargs: Any) -> list[dict[str, Any]]:
            return [{"ann_date": "20250801", "title": "future"}]

    class _CleanPipeline:
        def run(self, **kwargs: Any) -> dict[str, Any]:
            tushare = kwargs["tushare_adapter"]
            _ = tushare.fetch_announcements(ts_code="600519.SH")
            return {"target_overview": {"narrative": "clean narrative no leak"}}

    runner = BacktestRunner(
        swapper=_DummySwapper(),  # type: ignore[arg-type]
        tushare_inner=_LeakyTushare(),
        kb_inner=_DummyKB(),
        db_path=db,
        pipeline=_CleanPipeline(),
        metric_registry=MetricRegistry([]),
        enable_leak_detection=True,
    )
    case = BacktestCase(
        case_id=f"bt-{uuid4().hex[:8]}",
        ts_code="600519.SH",
        target_name="茅台",
        cut_off_date=date(2024, 6, 30),
    )
    run_id = runner.run_one(
        case=case,
        evaluator_llm="gpt-4o-2024-05-13",
        ablation_variant="V0_baseline",
        git_sha="testsha",
    )
    with sqlite3.connect(db) as con:
        con.row_factory = sqlite3.Row
        r = con.execute("SELECT status FROM backtest_runs WHERE run_id = ?", (run_id,)).fetchone()
    assert r["status"] == "completed"


def test_run_one_leakdetector_fires_when_pipeline_leaks_date_in_narrative(tmp_path) -> None:
    """LeakDetector should raise AssertionError if pipeline output narrative includes
    a date > cut_off (e.g. agent hallucinated 'as of 2025-08-01' for a 2024-06-30 case).
    """
    db = tmp_path / "eval.db"
    from app.services.eval_recorder import EvalRecorder

    EvalRecorder(db).init_schema()

    class _LeakingPipeline:
        def run(self, **kwargs: Any) -> dict[str, Any]:
            return {
                "target_overview": {
                    "narrative": "茅台报告 (含未来日期 2025-08-01 — 应触发 leak detector)",
                },
            }

    runner = BacktestRunner(
        swapper=_DummySwapper(),  # type: ignore[arg-type]
        tushare_inner=_DummyTushare(),
        kb_inner=_DummyKB(),
        db_path=db,
        pipeline=_LeakingPipeline(),
        metric_registry=MetricRegistry([]),
        enable_leak_detection=True,
    )
    case = BacktestCase(
        case_id=f"bt-{uuid4().hex[:8]}",
        ts_code="600519.SH",
        target_name="茅台",
        cut_off_date=date(2024, 6, 30),
    )
    with pytest.raises(AssertionError, match="data leakage"):
        runner.run_one(
            case=case,
            evaluator_llm="gpt-4o-2024-05-13",
            ablation_variant="V0_baseline",
            git_sha="testsha",
        )
    # run row written with status=failed
    with sqlite3.connect(db) as con:
        con.row_factory = sqlite3.Row
        r = con.execute(
            "SELECT status FROM backtest_runs WHERE git_sha = ?", ("testsha",)
        ).fetchone()
    assert r["status"] == "failed"
