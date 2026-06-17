"""窗口定义 + 指标×窗口合法配对矩阵。

评估问题生成时,用于约束"哪个指标能配哪个时间窗口"。
例如 CAGR(复合年增长率)需要 >=2 年才有意义,所以只允许配近三年。
"""

from __future__ import annotations

# 窗口码 -> 中文名
WINDOWS: dict[str, str] = {
    "3m": "近三个月",
    "1y": "近一年",
    "3y": "近三年",
}

# 指标 -> 其合法窗口集合
LEGAL: dict[str, frozenset[str]] = {
    "涨幅": frozenset({"3m", "1y", "3y"}),
    "回撤": frozenset({"3m", "1y", "3y"}),
    "波动": frozenset({"3m", "1y", "3y"}),
    "相关": frozenset({"3m", "1y", "3y"}),
    "CAGR": frozenset({"3y"}),  # CAGR 只配近三年(需 >=2 年才有意义)
}


def is_legal(indicator: str, window: str) -> bool:
    """指标与窗口是否构成合法配对。

    indicator 不在 LEGAL 或 window 不在其窗口集合 -> False。
    """
    return window in LEGAL.get(indicator, frozenset())


def window_cn(window: str) -> str:
    """窗口码 -> 中文名;非法码 raise KeyError。"""
    return WINDOWS[window]
