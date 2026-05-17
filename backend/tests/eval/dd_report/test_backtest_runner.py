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
        evaluator_llm="deepseek-v4-flash",
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
    assert row["llm_model"] == "deepseek-v4-flash"


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
        evaluator_llm="qwen-plus",
        ablation_variant="V0_baseline",
        git_sha="abc1234",
    )

    pipeline_mock.run.assert_called_once()
    kwargs = pipeline_mock.run.call_args.kwargs
    assert "tushare_adapter" in kwargs
    assert "kb_adapter" in kwargs
    assert "evaluator_client" in kwargs
    assert kwargs["evaluator_client"].model == "qwen-plus"


def test_backtest_run_passes_leak_detector_with_clean_data(tmp_db: Path) -> None:
    """跑一个 case, 用 LeakDetector 审查 tushare/kb 返回行无 leak."""
    from datetime import date
    from unittest.mock import MagicMock

    from eval.dd_report.backtest_runner import BacktestCase, BacktestRunner
    from eval.dd_report.leak_detector import LeakDetector
    from eval.dd_report.llm_swapper import LLMSwapper

    tushare_inner = MagicMock()
    tushare_inner.income.return_value = [{"ann_date": "20240315", "ts_code": "600519.SH"}]
    tushare_inner.daily.return_value = [{"trade_date": "20240329", "close": 1700.0}]

    kb_inner = MagicMock()
    kb_inner.search.return_value = []

    pipeline = MagicMock()
    pipeline.run.return_value = {"target_name": "贵州茅台"}

    runner = BacktestRunner(
        swapper=LLMSwapper(api_key="test"),
        tushare_inner=tushare_inner,
        kb_inner=kb_inner,
        db_path=tmp_db,
        pipeline=pipeline,
    )

    case = BacktestCase(
        case_id="bt-smoke-001",
        ts_code="600519.SH",
        target_name="贵州茅台",
        cut_off_date=date(2024, 6, 30),
    )
    runner.run_one(
        case=case,
        evaluator_llm="deepseek-v4-flash",
        ablation_variant="V0_baseline",
        git_sha="smoke",
    )

    detector = LeakDetector(cut_off=date(2024, 6, 30))
    income_rows = tushare_inner.income.return_value
    daily_rows = tushare_inner.daily.return_value

    leaks = detector.scan_tushare_rows(income_rows) + detector.scan_tushare_rows(daily_rows)
    detector.assert_no_leaks(leaks)


def test_backtest_run_fails_leak_detector_with_polluted_data(tmp_db: Path) -> None:
    """如果数据带 leak, detector 必须 catch."""
    from datetime import date

    import pytest
    from eval.dd_report.leak_detector import LeakDetector

    detector = LeakDetector(cut_off=date(2024, 6, 30))
    polluted = [{"ann_date": "20240715", "ts_code": "600519.SH"}]
    leaks = detector.scan_tushare_rows(polluted)
    with pytest.raises(AssertionError, match="data leakage detected"):
        detector.assert_no_leaks(leaks)
