"""组合算子层 —— 架在 indicator_oracle 上的多股/排序/筛选派发。

spec: docs/superpowers/specs/2026-06-17-question-gen-mvp-design.md
oracle 给单序列标准公式;本层负责:中文指标名 → oracle 派发(single)、
两股相关(correlation_pair)、跨股排序(rank_by)、多条件筛选(filter_by)。

per_stock 数据形状:
    {ts_code: {"close": [float...], "dates": [str...], "pct_chg": [float...]}}
"""

from __future__ import annotations

from eval import indicator_oracle

# 中文指标名集合(派发用)。CAGR 同时接受中文/英文写法。
_RETURN_NAMES = {"涨幅"}
_DRAWDOWN_NAMES = {"回撤"}
_VOL_NAMES = {"波动"}
_CAGR_NAMES = {"CAGR", "cagr"}


def single(indicator: str, data: dict, *, years: float = 1.0) -> float:
    """单股单指标派发到 oracle。

    涨幅 -> interval_return(close);回撤 -> max_drawdown(close);
    波动 -> annual_volatility(pct_chg);CAGR -> cagr(close, years);
    未知指标 raise ValueError。
    """
    if indicator in _RETURN_NAMES:
        return indicator_oracle.interval_return(data["close"])
    if indicator in _DRAWDOWN_NAMES:
        return indicator_oracle.max_drawdown(data["close"])
    if indicator in _VOL_NAMES:
        return indicator_oracle.annual_volatility(data["pct_chg"])
    if indicator in _CAGR_NAMES:
        return indicator_oracle.cagr(data["close"], years)
    raise ValueError(f"未知指标:{indicator!r}")


def correlation_pair(a: dict, b: dict) -> float:
    """两股日收益相关性(Pearson),委托 oracle.correlation 按 trade_date 对齐。"""
    return indicator_oracle.correlation(a["dates"], a["pct_chg"], b["dates"], b["pct_chg"])


def rank_by(
    indicator: str, per_stock: dict, top_k: int, descending: bool = True
) -> list[tuple[str, float]]:
    """对 per_stock 每只算 single(indicator) -> 按值排序取前 top_k。

    返回 [(ts_code, 值)],默认降序。
    """
    scored = [(ts_code, single(indicator, data)) for ts_code, data in per_stock.items()]
    scored.sort(key=lambda kv: kv[1], reverse=descending)
    return scored[:top_k]


def filter_by(per_stock: dict, predicates: list[tuple[str, str, float]]) -> set[str]:
    """多条件筛选:predicate=(indicator, op, threshold),op ∈ {">", "<"}。

    每只算各 indicator,全部 predicate 满足才入集;返回 ts_code 集合。
    """
    result: set[str] = set()
    for ts_code, data in per_stock.items():
        if all(_satisfies(single(ind, data), op, thr) for ind, op, thr in predicates):
            result.add(ts_code)
    return result


def _satisfies(value: float, op: str, threshold: float) -> bool:
    if op == ">":
        return value > threshold
    if op == "<":
        return value < threshold
    raise ValueError(f"未知比较符:{op!r}")


__all__ = ["single", "correlation_pair", "rank_by", "filter_by"]
