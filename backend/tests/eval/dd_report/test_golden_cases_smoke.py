"""Golden case file smoke test — Phase 1 Task 1.8."""

from __future__ import annotations

import json
from pathlib import Path

GOLDEN_PATH = Path(__file__).parents[3] / "eval" / "dd_report" / "golden" / "backtest_cases.jsonl"


def _load_cases() -> list[dict[str, str]]:
    return [
        json.loads(line)
        for line in GOLDEN_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_golden_cases_file_exists() -> None:
    assert GOLDEN_PATH.exists(), f"missing {GOLDEN_PATH}"


def test_golden_cases_count_32_backtest_plus_8_sanity() -> None:
    cases = _load_cases()
    backtest = [c for c in cases if c["case_type"] == "backtest"]
    sanity = [c for c in cases if c["case_type"] == "sanity"]
    assert len(backtest) == 32, f"expected 32 backtest case, got {len(backtest)}"
    assert len(sanity) == 8, f"expected 8 sanity case, got {len(sanity)}"


def test_golden_cases_8_companies_each() -> None:
    cases = _load_cases()
    expected = {
        "600519.SH",
        "300750.SZ",
        "601088.SH",
        "600221.SH",
        "600518.SH",
        "600036.SH",
        "600276.SH",
        "002415.SZ",
    }
    assert {c["ts_code"] for c in cases} == expected


def test_golden_cases_4_backtest_timepoints() -> None:
    cases = _load_cases()
    backtest_cuts = {c["cut_off_date"] for c in cases if c["case_type"] == "backtest"}
    assert backtest_cuts == {"2024-06-30", "2024-12-31", "2025-06-30", "2025-12-31"}


def test_golden_cases_sanity_cut_off_2026_04_30() -> None:
    cases = _load_cases()
    sanity_cuts = {c["cut_off_date"] for c in cases if c["case_type"] == "sanity"}
    assert sanity_cuts == {"2026-04-30"}


def test_golden_case_fields_complete() -> None:
    """每 case 必含 case_id / ts_code / target_name / cut_off_date / case_type / company_type."""
    cases = _load_cases()
    required = {"case_id", "ts_code", "target_name", "cut_off_date", "case_type", "company_type"}
    for c in cases:
        assert required.issubset(c.keys()), f"case {c.get('case_id')} missing {required - c.keys()}"
