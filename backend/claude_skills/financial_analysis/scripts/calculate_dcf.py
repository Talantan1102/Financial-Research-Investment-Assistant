"""DCF (Discounted Cash Flow) valuation script — L3b skill demo.

Wire format:
    stdin  <- JSON {
        "free_cash_flows": [num, ...],
        "wacc": float,
        "terminal_growth": float,
        "shares_outstanding": int,
        "net_debt": float
    }
    stdout -> JSON {
        "enterprise_value": float,
        "equity_value": float,
        "per_share": float,
        "terminal_value": float,
        "pv_of_terminal_value": float,
        "pv_of_explicit_fcfs": float,
        "horizon_years": int
    }
"""

from __future__ import annotations

import json
import sys
from typing import Any


def _validate(data: dict[str, Any]) -> dict[str, Any]:
    required = ["free_cash_flows", "wacc", "terminal_growth", "shares_outstanding", "net_debt"]
    for k in required:
        if k not in data:
            raise ValueError(f"missing field: {k}")
    fcfs = data["free_cash_flows"]
    if not isinstance(fcfs, list) or len(fcfs) == 0:
        raise ValueError("free_cash_flows must be a non-empty list of numbers")
    for f in fcfs:
        if not isinstance(f, (int, float)):
            raise ValueError(f"free_cash_flow not a number: {f!r}")
    for k in ("wacc", "terminal_growth", "net_debt"):
        if not isinstance(data[k], (int, float)):
            raise ValueError(f"{k} must be a number; got {type(data[k]).__name__}")
    if not isinstance(data["shares_outstanding"], int) or data["shares_outstanding"] <= 0:
        raise ValueError("shares_outstanding must be a positive int")
    if data["wacc"] <= data["terminal_growth"]:
        raise ValueError("wacc must exceed terminal_growth (Gordon constraint)")
    return data


def calculate_dcf(
    free_cash_flows: list[float],
    wacc: float,
    terminal_growth: float,
    shares_outstanding: int,
    net_debt: float,
) -> dict[str, float | int]:
    n = len(free_cash_flows)
    pv_explicit = 0.0
    for i, fcf in enumerate(free_cash_flows, start=1):
        pv_explicit += fcf / ((1 + wacc) ** i)

    fcf_n = free_cash_flows[-1]
    terminal_value = fcf_n * (1 + terminal_growth) / (wacc - terminal_growth)
    pv_terminal = terminal_value / ((1 + wacc) ** n)

    enterprise_value = pv_explicit + pv_terminal
    equity_value = enterprise_value - net_debt
    per_share = equity_value / shares_outstanding

    return {
        "enterprise_value": round(enterprise_value, 4),
        "equity_value": round(equity_value, 4),
        "per_share": round(per_share, 4),
        "terminal_value": round(terminal_value, 4),
        "pv_of_terminal_value": round(pv_terminal, 4),
        "pv_of_explicit_fcfs": round(pv_explicit, 4),
        "horizon_years": n,
    }


def main() -> int:
    try:
        raw = sys.stdin.read()
        data = json.loads(raw)
        data = _validate(data)
        out = calculate_dcf(
            free_cash_flows=data["free_cash_flows"],
            wacc=float(data["wacc"]),
            terminal_growth=float(data["terminal_growth"]),
            shares_outstanding=int(data["shares_outstanding"]),
            net_debt=float(data["net_debt"]),
        )
        print(json.dumps(out))
        return 0
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"calculate_dcf invalid input: {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
