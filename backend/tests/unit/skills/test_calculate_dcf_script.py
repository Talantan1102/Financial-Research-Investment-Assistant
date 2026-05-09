"""L0 — calculate_dcf.py unit-level value correctness."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def script_path() -> Path:
    return (
        Path(__file__).resolve().parents[3]
        / "claude_skills"
        / "financial_analysis"
        / "scripts"
        / "calculate_dcf.py"
    )


def _run(script: Path, payload: dict) -> dict:
    proc = subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(payload).encode(),
        capture_output=True,
        timeout=15,
    )
    assert proc.returncode == 0, f"stderr: {proc.stderr.decode()}"
    return json.loads(proc.stdout)


def test_calculate_dcf_basic(script_path):
    out = _run(
        script_path,
        {
            "free_cash_flows": [100, 110, 121, 133, 146],
            "wacc": 0.10,
            "terminal_growth": 0.03,
            "shares_outstanding": 1000,
            "net_debt": 0,
        },
    )
    assert "enterprise_value" in out
    assert "equity_value" in out
    assert "per_share" in out
    assert out["enterprise_value"] > 0
    assert out["equity_value"] == out["enterprise_value"] - 0
    assert abs(out["per_share"] - out["equity_value"] / 1000) < 0.01


def test_calculate_dcf_terminal_value_matches_gordon(script_path):
    out = _run(
        script_path,
        {
            "free_cash_flows": [100],
            "wacc": 0.10,
            "terminal_growth": 0.02,
            "shares_outstanding": 100,
            "net_debt": 0,
        },
    )
    # FCF_1 PV = 100 / 1.1 ≈ 90.91
    # TV at end of year 1 = 100 * 1.02 / (0.10 - 0.02) = 1275
    # PV(TV) = 1275 / 1.1 ≈ 1159.09
    # EV ≈ 1250
    assert abs(out["enterprise_value"] - 1250.0) < 1.0


def test_calculate_dcf_handles_net_debt(script_path):
    out = _run(
        script_path,
        {
            "free_cash_flows": [100, 100, 100],
            "wacc": 0.10,
            "terminal_growth": 0.02,
            "shares_outstanding": 1000,
            "net_debt": 500,
        },
    )
    assert out["equity_value"] == out["enterprise_value"] - 500


def test_calculate_dcf_invalid_input_exits_nonzero(script_path):
    proc = subprocess.run(
        [sys.executable, str(script_path)],
        input=b'{"wacc": "not a number"}',
        capture_output=True,
        timeout=10,
    )
    assert proc.returncode != 0
    assert b"error" in proc.stderr.lower() or b"invalid" in proc.stderr.lower()
