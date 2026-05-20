"""LeakDetector unit tests — Phase 1 Task 1.7.

spec § 4.5 决策 5 / § 7.4 backtest 数据 leak detector
"""

from __future__ import annotations

from datetime import date

import pytest


def test_leak_detector_detects_ann_date_after_cutoff() -> None:
    from eval.dd_report.leak_detector import LeakDetector

    detector = LeakDetector(cut_off=date(2024, 6, 30))
    rows = [
        {"ann_date": "20240501", "source": "tushare:income"},
        {"ann_date": "20240715", "source": "tushare:income"},
    ]
    leaks = detector.scan_tushare_rows(rows)

    assert len(leaks) == 1
    assert leaks[0].value == "20240715"


def test_leak_detector_detects_chunk_publish_date_after_cutoff() -> None:
    from eval.dd_report.leak_detector import LeakDetector

    detector = LeakDetector(cut_off=date(2024, 6, 30))
    chunks = [
        {"chunk_id": "c1", "publish_date": date(2024, 3, 30)},
        {"chunk_id": "c2", "publish_date": date(2024, 9, 30)},
    ]
    leaks = detector.scan_chunks(chunks)
    assert len(leaks) == 1
    assert leaks[0].source == "kb:c2"


def test_leak_detector_detects_future_dates_in_prompt_text() -> None:
    """LLM prompt 文本中出现 cut_off 之后的具体日期视为 leak signal."""
    from eval.dd_report.leak_detector import LeakDetector

    detector = LeakDetector(cut_off=date(2024, 6, 30))
    prompt = "茅台 2024-08-15 公告显示分红比例提升至 80%"
    leaks = detector.scan_prompt_text(prompt, source="agent:writer:prompt")
    assert any("2024-08-15" in leak.value for leak in leaks)


def test_leak_detector_no_false_positive_on_dates_before_cutoff() -> None:
    from eval.dd_report.leak_detector import LeakDetector

    detector = LeakDetector(cut_off=date(2024, 6, 30))
    prompt = "茅台 2024-03-15 公告显示"
    leaks = detector.scan_prompt_text(prompt, source="agent:writer:prompt")
    assert leaks == []


def test_leak_detector_assertion_helper() -> None:
    """assert_no_leaks 在 leak 存在时 raise AssertionError."""
    from eval.dd_report.leak_detector import LeakDetector

    detector = LeakDetector(cut_off=date(2024, 6, 30))
    rows = [{"ann_date": "20240715", "source": "tushare:income"}]
    with pytest.raises(AssertionError, match="data leakage detected"):
        detector.assert_no_leaks(detector.scan_tushare_rows(rows))
