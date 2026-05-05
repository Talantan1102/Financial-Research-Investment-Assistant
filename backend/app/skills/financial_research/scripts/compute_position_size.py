"""Pure deterministic position-size calculator.

Formula:
    position_pct = base_pct[rec] * risk_multiplier[tol] *
                   (small_cap_haircut if mc < threshold else 1.0)
    capped at max_position_pct.

YAML rules loaded once at module import.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml

Recommendation = Literal[
    "recommend_buy",
    "recommend_overweight",
    "recommend_hold",
    "recommend_underweight",
    "recommend_sell",
]
RiskTolerance = Literal[
    "conservative",
    "moderate",
    "balanced",
    "aggressive",
    "very_aggressive",
]

_RULES_PATH = Path(__file__).parent.parent / "references" / "position_size_rules.yaml"
_RULES: dict[str, Any] = yaml.safe_load(_RULES_PATH.read_text(encoding="utf-8"))


def compute_position_size_pct(
    *,
    recommendation: Recommendation,
    risk_tolerance: RiskTolerance,
    market_cap_cny: float,
) -> float:
    """Return suggested position size as a percentage of portfolio.

    Args:
        recommendation: One of the 5 rating literals (e.g. ``recommend_buy``).
        risk_tolerance: One of 5 user persona tolerance literals
            (``conservative`` … ``very_aggressive``).
        market_cap_cny: Stock market cap in CNY (yuan).

    Returns:
        Position size in percent (0.0 to ``max_position_pct``).
    """
    base_pct: float = float(_RULES["base_pct"][recommendation])
    multiplier: float = float(_RULES["risk_multiplier"][risk_tolerance])
    threshold: float = float(_RULES["small_cap_threshold_cny"])
    haircut: float = float(_RULES["small_cap_haircut"])
    cap: float = float(_RULES["max_position_pct"])

    size_factor: float = haircut if market_cap_cny < threshold else 1.0
    pct: float = base_pct * multiplier * size_factor
    return min(pct, cap)
