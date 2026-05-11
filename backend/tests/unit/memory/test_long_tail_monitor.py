"""L0: 长尾召回监控 — spec § 11 #3 验证 acceptance."""

from __future__ import annotations

from app.memory.long_tail_monitor import (
    LONG_TAIL_P90_THRESHOLD_DAYS,
    LongTailReport,
    compute_long_tail_metrics,
)


class TestComputeLongTailMetrics:
    def test_threshold_default_7_days(self) -> None:
        assert LONG_TAIL_P90_THRESHOLD_DAYS == 7

    def test_all_recent_triggers_alert(self) -> None:
        """top-5 valid_from 全 ≤ 7 天 → P90 ≤ 7 → alert."""
        sample_logs = [
            {"top_k_valid_from_p90_days": 3.0},
            {"top_k_valid_from_p90_days": 2.5},
            {"top_k_valid_from_p90_days": 4.0},
        ]
        report = compute_long_tail_metrics(sample_logs)
        assert report.alert is True
        assert report.median_p90_days < LONG_TAIL_P90_THRESHOLD_DAYS

    def test_diverse_distribution_no_alert(self) -> None:
        """top-5 散布 30-365 天 → no alert."""
        sample_logs = [
            {"top_k_valid_from_p90_days": 30.0},
            {"top_k_valid_from_p90_days": 90.0},
            {"top_k_valid_from_p90_days": 200.0},
            {"top_k_valid_from_p90_days": 365.0},
        ]
        report = compute_long_tail_metrics(sample_logs)
        assert report.alert is False
        assert report.median_p90_days > 30

    def test_empty_sample_no_op(self) -> None:
        report = compute_long_tail_metrics([])
        assert report.alert is False
        assert report.sample_count == 0

    def test_report_includes_sample_count(self) -> None:
        report = compute_long_tail_metrics(
            [
                {"top_k_valid_from_p90_days": 100.0},
                {"top_k_valid_from_p90_days": 50.0},
            ]
        )
        assert report.sample_count == 2

    def test_passing_property(self) -> None:
        passing_report = LongTailReport(
            sample_count=2,
            median_p90_days=100.0,
            alert=False,
            samples_below_threshold_pct=0.0,
        )
        assert passing_report.passing is True

        alerting_report = LongTailReport(
            sample_count=2,
            median_p90_days=2.0,
            alert=True,
            samples_below_threshold_pct=1.0,
        )
        assert alerting_report.passing is False

    def test_pct_below_threshold_calculated(self) -> None:
        sample_logs = [
            {"top_k_valid_from_p90_days": 1.0},
            {"top_k_valid_from_p90_days": 2.0},
            {"top_k_valid_from_p90_days": 100.0},
            {"top_k_valid_from_p90_days": 200.0},
        ]
        report = compute_long_tail_metrics(sample_logs)
        assert report.samples_below_threshold_pct == 0.5  # 2/4
