"""BacktestMetricScores Pydantic schema — Phase 2 T2.0.

去推荐改造(2026-06-04):预测回测(原 M4 方向/目标价命中/风险预警)整把尺子下线,
schema 现在只覆盖 M1/M2/M3/M5 四把尺子。
"""

from __future__ import annotations

from eval.dd_report.metric_scores import BacktestMetricScores


def test_schema_accepts_all_metric_scores() -> None:
    s = BacktestMetricScores(
        m1_citation_precision=0.92,
        m1_citation_recall=0.85,
        m2_numerical_accuracy=0.90,
        m2_numerical_total=20,
        m2_numerical_correct=18,
        m3_risk_pairing_score=0.71,
        m5_composite_mean=7.6,
        m5_composite_majority=8.0,
        m5_composite_disagreement_max=2.0,
    )
    j = s.model_dump_json()
    assert "m1_citation_precision" in j


def test_details_json_round_trips() -> None:
    s = BacktestMetricScores(
        m1_citation_precision=0.5,
        m1_citation_recall=0.5,
        m2_numerical_accuracy=0.5,
        m2_numerical_total=2,
        m2_numerical_correct=1,
        m3_risk_pairing_score=0.5,
        m5_composite_mean=5.0,
        m5_composite_majority=5.0,
        m5_composite_disagreement_max=1.0,
        details_json={"m1_failed_cites": ["chunk-x"]},
    )
    roundtripped = BacktestMetricScores.model_validate_json(s.model_dump_json())
    assert roundtripped.details_json == {"m1_failed_cites": ["chunk-x"]}


def test_eval_result_persists_metric_scores_json(db_session) -> None:
    import contextlib
    from datetime import UTC, datetime

    from app.services.eval_models import EvalResult, JudgeScores
    from app.services.eval_recorder import EvalRecorder

    recorder = EvalRecorder(session_factory=lambda: contextlib.nullcontext(db_session))
    scores = BacktestMetricScores(
        m1_citation_precision=0.9,
        m1_citation_recall=0.8,
        m2_numerical_accuracy=0.85,
        m2_numerical_total=10,
        m2_numerical_correct=8,
        m3_risk_pairing_score=0.7,
        m5_composite_mean=7.5,
        m5_composite_majority=8.0,
        m5_composite_disagreement_max=1.0,
    )
    result = EvalResult(
        eval_id="ev-1",
        request_id="req-1",
        case_id="bt-test",
        scores=JudgeScores(
            factuality=0,
            factuality_evidence="N/A backtest",
            tool_correctness=None,
            tool_correctness_evidence="N/A backtest",
            coverage=0,
            coverage_evidence="N/A backtest",
            structure=0,
            structure_evidence="N/A backtest",
        ),
        judge_model="backtest",
        judge_cost_cny=0.0,
        judge_latency_ms=0,
        timestamp=datetime.now(UTC),
        backtest_run_id="bt-run-x",
        cut_off_date="2024-06-30",
        evaluator_llm="deepseek-v4-flash",
        case_type="backtest",
        metric_scores_json=scores.model_dump_json(),
    )
    recorder.write(result)
    read = recorder.read("ev-1")
    assert read.metric_scores_json is not None
    BacktestMetricScores.model_validate_json(read.metric_scores_json)
