"""YAML-rules-driven 5-tier recommendation classifier.

Mini DSL:
    - condition: ``{field, op, value}`` triple OR ``{count_at_least_3: [...]}``
    - rule: ``all_of`` / ``any_of`` list of conditions OR ``fallback: true``
    - op: ``<``, ``>``, ``==``, ``<=``, ``>=``

Priority: rule order in the YAML list (first match wins).
"""

from __future__ import annotations

from collections.abc import Callable
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

_RULES_PATH = Path(__file__).parent.parent / "references" / "recommendation_rules.yaml"
_RULES_DOC: dict[str, Any] = yaml.safe_load(_RULES_PATH.read_text(encoding="utf-8"))
_RULES: list[dict[str, Any]] = list(_RULES_DOC["rules"])

_OPS: dict[str, Callable[[Any, Any], bool]] = {
    "<": lambda a, b: a < b,
    ">": lambda a, b: a > b,
    "==": lambda a, b: a == b,
    "<=": lambda a, b: a <= b,
    ">=": lambda a, b: a >= b,
}


def _eval_condition(cond: dict[str, Any], metrics: dict[str, Any]) -> bool:
    if "count_at_least_3" in cond:
        sub_conds: list[dict[str, Any]] = list(cond["count_at_least_3"])
        hits = sum(1 for c in sub_conds if _eval_condition(c, metrics))
        return hits >= 3
    field: str = cond["field"]
    op: str = cond["op"]
    value: Any = cond["value"]
    if field not in metrics:
        return False
    return _OPS[op](metrics[field], value)


def _eval_rule(rule: dict[str, Any], metrics: dict[str, Any]) -> bool:
    if rule.get("fallback") is True:
        return True
    if "all_of" in rule:
        return all(_eval_condition(c, metrics) for c in rule["all_of"])
    if "any_of" in rule:
        return any(_eval_condition(c, metrics) for c in rule["any_of"])
    return False


def classify_recommendation(metrics: dict[str, Any]) -> Recommendation:
    """Classify a metrics dict into one of 5 recommendation literals.

    Args:
        metrics: Dict of computed indicators. Common keys:
            ``pe_percentile`` (0..1), ``roe`` (e.g. 0.18),
            ``revenue_yoy`` (e.g. 0.12), ``net_profit_yoy``,
            ``forecast_signal`` (``"positive"|"neutral"|"negative"``),
            ``pledge_ratio``, ``asset_liability_warning`` (bool).

    Returns:
        Recommendation literal — first matching rule in priority order.
    """
    for rule in _RULES:
        if _eval_rule(rule, metrics):
            name: str = rule["name"]
            # narrow str → Recommendation Literal via cast-ish assert
            assert name in (
                "recommend_buy",
                "recommend_overweight",
                "recommend_hold",
                "recommend_underweight",
                "recommend_sell",
            ), f"Unknown rule name: {name}"
            return name  # type: ignore[return-value]
    # Should never happen — recommend_hold is fallback. Defensive default.
    return "recommend_hold"
