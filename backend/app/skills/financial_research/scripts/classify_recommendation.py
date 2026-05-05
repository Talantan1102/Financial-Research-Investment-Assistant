"""YAML-rules-driven 5-tier recommendation classifier.

Mini DSL:
    - condition: ``{field, op, value}`` triple OR ``{count_at_least_3: [...]}``
    - rule envelope: ``{description, conditions: {all_of|any_of: [...]}}`` OR
      ``{description, fallback: true}``
    - op: ``<``, ``>``, ``==``, ``<=``, ``>=``

Priority is hard-coded in ``_PRIORITY`` (NOT YAML mapping order) so future
edits to recommendation_rules.yaml cannot silently re-order evaluation.
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
_RULES: dict[str, dict[str, Any]] = dict(_RULES_DOC["rules"])

_OPS: dict[str, Callable[[Any, Any], bool]] = {
    "<": lambda a, b: a < b,
    ">": lambda a, b: a > b,
    "==": lambda a, b: a == b,
    "<=": lambda a, b: a <= b,
    ">=": lambda a, b: a >= b,
}

# 评级优先级顺序(先 sell 红线, 再 buy / overweight, 最后 underweight, 兜底 hold)
# Hard-coded so YAML mapping order can't silently shift priority.
_PRIORITY: list[Recommendation] = [
    "recommend_sell",
    "recommend_buy",
    "recommend_overweight",
    "recommend_underweight",
    "recommend_hold",
]


def _eval_condition(cond: dict[str, Any], metrics: dict[str, Any]) -> bool:
    if "count_at_least_3" in cond:
        sub_conds: list[dict[str, Any]] = list(cond["count_at_least_3"])
        hits = sum(1 for c in sub_conds if _eval_condition(c, metrics))
        return hits >= 3
    field: str = cond["field"]
    op: str = cond["op"]
    value: Any = cond["value"]
    val = metrics.get(field)
    if val is None:
        return False
    try:
        return bool(_OPS[op](val, value))
    except TypeError:
        # 类型不匹配 (e.g. str compared with float) → no-match.
        return False


def _eval_rule(rule: dict[str, Any], metrics: dict[str, Any]) -> bool:
    if rule.get("fallback") is True:
        return True
    conds: dict[str, Any] = rule.get("conditions", {})
    if "all_of" in conds:
        return all(_eval_condition(c, metrics) for c in conds["all_of"])
    if "any_of" in conds:
        return any(_eval_condition(c, metrics) for c in conds["any_of"])
    raise ValueError(
        f"unrecognized rule envelope (typo or unsupported shape?): "
        f"rule keys={list(rule.keys())}, conditions keys={list(conds.keys())}"
    )


def classify_recommendation(metrics: dict[str, Any]) -> Recommendation:
    """Classify a metrics dict into one of 5 recommendation literals.

    Args:
        metrics: Dict of computed indicators. Common keys:
            ``pe_percentile`` (0..1), ``roe`` (e.g. 0.18),
            ``revenue_yoy`` (e.g. 0.12), ``net_profit_yoy``,
            ``forecast_signal`` (``"positive"|"neutral"|"negative"``),
            ``pledge_ratio``, ``asset_liability_warning`` (bool).

    Returns:
        Recommendation literal — first matching rule in ``_PRIORITY`` order.
    """
    for rec in _PRIORITY:
        rule = _RULES.get(rec)
        if rule is None:
            continue
        if _eval_rule(rule, metrics):
            return rec
    # Should never reach — recommend_hold is fallback. Defensive default.
    return "recommend_hold"
