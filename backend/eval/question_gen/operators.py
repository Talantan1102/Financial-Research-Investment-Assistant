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

# 行情快照指标 -> daily_basic 列名(直取,非计算)。换手率/股息率 tushare 已是百分数,不再 scale。
_SNAPSHOT_COLUMNS: dict[str, str] = {
    "PE": "pe",
    "PB": "pb",
    "换手率": "turnover_rate",
    "股息率": "dv_ratio",
}


def single(indicator: str, data: dict, *, years: float = 1.0) -> float:
    """单股单指标派发到 oracle。

    涨幅 -> interval_return(close);回撤 -> max_drawdown(close);
    波动 -> annual_volatility(pct_chg);CAGR -> cagr(close, years);
    未知指标 raise ValueError。

    口径备注:涨幅/回撤/CAGR 用**不复权收盘价比值**(= 价格回报,与 agent 自然算法一致)。
    试过改 pct_chg 累乘的"复权路径"修拆股,但那是**含分红的总回报**,与价格回报差一个
    股息率(工行实测 6.87pp),把所有分红股错开 → 已回退。拆股票(比亚迪等)在不复权下
    回撤/涨幅会偏,作为已知基准限制(详见 pre-RL 基线文档)。
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


def snapshot_lookup(indicator: str, snap: dict) -> float:
    """行情快照取数:指标名 -> 直取 daily_basic 字段值。未知指标 raise ValueError。

    snap 形状: {"pe": float, "pb": float, "turnover_rate": float, "dv_ratio": float}。
    """
    col = _SNAPSHOT_COLUMNS.get(indicator)
    if col is None:
        raise ValueError(f"未知快照指标:{indicator!r}")
    return float(snap[col])


__all__ = ["single", "correlation_pair", "rank_by", "filter_by", "snapshot_lookup"]
