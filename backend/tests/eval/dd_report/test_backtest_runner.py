"""BacktestRunner skeleton tests — Phase 1 Task 1.6.

spec § 4.1 / § 5.1 / § 5.3
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """初始化包含 backtest_runs 表的临时 sqlite."""
    from app.services.eval_recorder import EvalRecorder

    db = tmp_path / "eval.sqlite"
    rec = EvalRecorder(db_path=db)
    rec.init_schema()
    return db


def test_backtest_runner_init(tmp_db: Path) -> None:
    """BacktestRunner 接受必要依赖."""
    from eval.dd_report.backtest_runner import BacktestRunner
    from eval.dd_report.llm_swapper import LLMSwapper

    swapper = LLMSwapper(api_key="test")
    runner = BacktestRunner(
        swapper=swapper,
        tushare_inner=MagicMock(),
        kb_inner=MagicMock(),
        db_path=tmp_db,
    )
    assert runner is not None


def test_backtest_runner_writes_run_row(tmp_db: Path) -> None:
    """run_one 完成后 backtest_runs 表写入一行 status='completed'."""
    from eval.dd_report.backtest_runner import BacktestCase, BacktestRunner
    from eval.dd_report.llm_swapper import LLMSwapper

    pipeline_mock = MagicMock()
    pipeline_mock.run.return_value = {"target_name": "贵州茅台", "target_ts_code": "600519.SH"}

    runner = BacktestRunner(
        swapper=LLMSwapper(api_key="test"),
        tushare_inner=MagicMock(),
        kb_inner=MagicMock(),
        db_path=tmp_db,
        pipeline=pipeline_mock,
    )

    case = BacktestCase(
        case_id="bt-600519-20240630",
        ts_code="600519.SH",
        target_name="贵州茅台",
        cut_off_date=date(2024, 6, 30),
    )
    run_id = runner.run_one(
        case=case,
        evaluator_llm="gpt-4o-2024-05-13",
        ablation_variant="V0_baseline",
        git_sha="abc1234",
    )

    assert run_id

    with sqlite3.connect(tmp_db) as con:
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT * FROM backtest_runs WHERE run_id = ?", (run_id,)).fetchone()

    assert row is not None
    assert row["status"] == "completed"
    assert row["case_count"] == 1
    assert row["git_sha"] == "abc1234"
    assert row["ablation_variant"] == "V0_baseline"
    assert row["llm_model"] == "gpt-4o-2024-05-13"


def test_backtest_runner_calls_pipeline_with_adapters(tmp_db: Path) -> None:
    """pipeline.run 收到包装好的 tushare_adapter + kb_adapter + evaluator_client."""
    from eval.dd_report.backtest_runner import BacktestCase, BacktestRunner
    from eval.dd_report.llm_swapper import LLMSwapper

    pipeline_mock = MagicMock()
    pipeline_mock.run.return_value = {"target_name": "宁德时代"}

    runner = BacktestRunner(
        swapper=LLMSwapper(api_key="test"),
        tushare_inner=MagicMock(),
        kb_inner=MagicMock(),
        db_path=tmp_db,
        pipeline=pipeline_mock,
    )

    case = BacktestCase(
        case_id="bt-300750-20240630",
        ts_code="300750.SZ",
        target_name="宁德时代",
        cut_off_date=date(2024, 6, 30),
    )
    runner.run_one(
        case=case,
        evaluator_llm="qwen2.5-72b-instruct",
        ablation_variant="V0_baseline",
        git_sha="abc1234",
    )

    pipeline_mock.run.assert_called_once()
    kwargs = pipeline_mock.run.call_args.kwargs
    assert "tushare_adapter" in kwargs
    assert "kb_adapter" in kwargs
    assert "evaluator_client" in kwargs
    assert kwargs["evaluator_client"].model == "qwen2.5-72b-instruct"
