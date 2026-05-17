"""BacktestMetricScores Pydantic schema — Phase 2 T2.0."""

from __future__ import annotations

from eval.dd_report.metric_scores import BacktestMetricScores


def test_schema_accepts_all_5_metric_scores() -> None:
    s = BacktestMetricScores(
        m1_citation_precision=0.92,
        m1_citation_recall=0.85,
        m2_numerical_accuracy=0.90,
        m2_numerical_total=20,
        m2_numerical_correct=18,
        m3_risk_pairing_score=0.71,
        m4_recommendation_direction_correct=True,
        m4_target_price_hit=False,
        m4_risk_flag_realized_rate=0.50,
        m5_composite_mean=7.6,
        m5_composite_majority=8.0,
        m5_composite_disagreement_max=2.0,
    )
    j = s.model_dump_json()
    assert "m1_citation_precision" in j


def test_schema_allows_partial_m4_none_when_not_applicable() -> None:
    s = BacktestMetricScores(
        m1_citation_precision=1.0,
        m1_citation_recall=1.0,
        m2_numerical_accuracy=1.0,
        m2_numerical_total=0,
        m2_numerical_correct=0,
        m3_risk_pairing_score=1.0,
        m4_recommendation_direction_correct=None,
        m4_target_price_hit=None,
        m4_risk_flag_realized_rate=None,
        m5_composite_mean=8.0,
        m5_composite_majority=8.0,
        m5_composite_disagreement_max=0.0,
    )
    assert s.m4_recommendation_direction_correct is None


def test_details_json_round_trips() -> None:
    s = BacktestMetricScores(
        m1_citation_precision=0.5,
        m1_citation_recall=0.5,
        m2_numerical_accuracy=0.5,
        m2_numerical_total=2,
        m2_numerical_correct=1,
        m3_risk_pairing_score=0.5,
        m4_recommendation_direction_correct=True,
        m4_target_price_hit=False,
        m4_risk_flag_realized_rate=0.0,
        m5_composite_mean=5.0,
        m5_composite_majority=5.0,
        m5_composite_disagreement_max=1.0,
        details_json={"m1_failed_cites": ["chunk-x"]},
    )
    roundtripped = BacktestMetricScores.model_validate_json(s.model_dump_json())
    assert roundtripped.details_json == {"m1_failed_cites": ["chunk-x"]}


def test_eval_result_persists_metric_scores_json(tmp_path) -> None:
    from datetime import datetime

    from app.services.eval_models import EvalResult, JudgeScores
    from app.services.eval_recorder import EvalRecorder

    db = tmp_path / "eval.db"
    recorder = EvalRecorder(db)
    recorder.init_schema()
    scores = BacktestMetricScores(
        m1_citation_precision=0.9,
        m1_citation_recall=0.8,
        m2_numerical_accuracy=0.85,
        m2_numerical_total=10,
        m2_numerical_correct=8,
        m3_risk_pairing_score=0.7,
        m4_recommendation_direction_correct=None,
        m4_target_price_hit=None,
        m4_risk_flag_realized_rate=None,
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
        timestamp=datetime.utcnow(),
        backtest_run_id="bt-run-x",
        cut_off_date="2024-06-30",
        evaluator_llm="gpt-4o-2024-05-13",
        case_type="backtest",
        metric_scores_json=scores.model_dump_json(),
    )
    recorder.write(result)
    read = recorder.read("ev-1")
    assert read.metric_scores_json is not None
    BacktestMetricScores.model_validate_json(read.metric_scores_json)
