"""Industry benchmark JSON lookup with DEFAULT fallback.

Loads industry_benchmarks.json once at module import. Returns float values
for known (industry, indicator) pairs and falls back to the ``DEFAULT``
industry profile when the requested industry or indicator is missing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_BENCHMARKS_PATH = Path(__file__).parent.parent / "references" / "industry_benchmarks.json"
_BENCHMARKS: dict[str, dict[str, Any]] = json.loads(_BENCHMARKS_PATH.read_text(encoding="utf-8"))


def lookup_industry_benchmark(*, industry: str, indicator: str) -> float:
    """Look up a numeric industry benchmark, falling back to DEFAULT.

    Args:
        industry: Industry name (Chinese), e.g. ``"白酒"``. Unknown industries
            fall back to ``DEFAULT``.
        indicator: Indicator key, e.g. ``"ROE_行业平均"``. Indicators missing
            from the requested industry also fall back to ``DEFAULT``.

    Returns:
        Float benchmark value.

    Raises:
        KeyError: If the indicator is missing from BOTH the requested industry
            AND ``DEFAULT``, OR if the indicator is a private metadata key
            (starts with ``_``, e.g. ``_note``) — these are intentionally
            unreachable as numeric lookups.
    """
    industry_data: dict[str, Any] = _BENCHMARKS.get(industry, _BENCHMARKS["DEFAULT"])
    if indicator in industry_data and not indicator.startswith("_"):
        return float(industry_data[indicator])
    # fall back to DEFAULT when indicator missing from this industry
    return float(_BENCHMARKS["DEFAULT"][indicator])
