"""GroundTruthLoader Phase 2 真实现 — T2.1."""

from __future__ import annotations

from datetime import date
from typing import Any

from eval.dd_report.golden.ground_truth_loader import GroundTruthLoader


class _FakeTushare:
    def __init__(self, kline: list[dict[str, Any]], anns: list[dict[str, Any]]) -> None:
        self._kline = kline
        self._anns = anns

    def daily(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self._kline

    def anns(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self._anns


def test_fetch_post_cut_off_kline_returns_rows_within_horizon() -> None:
    inner = _FakeTushare(
        kline=[
            {"trade_date": "20240701", "close": 1700.0},
            {"trade_date": "20240801", "close": 1650.0},
            {"trade_date": "20241001", "close": 1500.0},  # beyond horizon 90d
        ],
        anns=[],
    )
    loader = GroundTruthLoader(inner=inner)
    rows = loader.fetch_post_cut_off_kline("600519.SH", date(2024, 6, 30), horizon_days=90)
    dates = [r["trade_date"] for r in rows]
    assert "20240701" in dates
    assert "20240801" in dates
    assert "20241001" not in dates


def test_fetch_post_cut_off_anns_filters_pre_cut_off() -> None:
    inner = _FakeTushare(
        kline=[],
        anns=[
            {"ann_date": "20240615", "title": "前公告 ignore"},
            {"ann_date": "20240715", "title": "中报披露"},
            {"ann_date": "20241105", "title": "退市风险警告"},  # within 180d
            {"ann_date": "20260101", "title": "远未来"},
        ],
    )
    loader = GroundTruthLoader(inner=inner)
    rows = loader.fetch_post_cut_off_anns("600519.SH", date(2024, 6, 30), horizon_days=180)
    titles = [r["title"] for r in rows]
    assert "前公告 ignore" not in titles
    assert "中报披露" in titles
    assert "退市风险警告" in titles
    assert "远未来" not in titles


def test_fetch_returns_empty_when_no_data() -> None:
    inner = _FakeTushare(kline=[], anns=[])
    loader = GroundTruthLoader(inner=inner)
    assert loader.fetch_post_cut_off_kline("X", date(2024, 6, 30)) == []
    assert loader.fetch_post_cut_off_anns("X", date(2024, 6, 30)) == []
