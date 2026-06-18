"""验证集独立 oracle —— 冻结口径的纯函数参考实现。

spec: docs/superpowers/specs/2026-06-16-computation-caliber-freeze-design.md
不依赖被测代码;只吃数据、套固定公式,给验证集/pass@k 出"标准答案"。

冻结口径(全模块一致):
- 收益率 = tushare pct_chg ÷ 100(第一根参照窗口前一天;别用 close 比值——M1 0.018 的根);
- 窗口 = 调用方传入(method B:用 agent 实际 get_daily 数据,窗口同源);
- 涨幅/回撤/CAGR 走**复权路径**(adjusted_path:pct_chg 累乘,剔除拆股/除息假跳变);
  波动/相关直接用 pct_chg;年化 √252;标准差 ddof=1;分位 < 不插值。
返回值口径:涨幅/回撤/波动/CAGR 为**分数**(×100 得 %);相关无量纲;分位 ∈ [0,1]。
"""

from __future__ import annotations

import numpy as np

_TRADING_DAYS = 252


def adjusted_path(pct_chg: list[float]) -> list[float]:
    """从日涨跌幅(tushare %-值)累乘出复权价格路径,剔除拆股/除息的假跳变。

    基准 1.0;首根 pct_chg 参照窗口前一天(窗外),故从次日起累乘,
    使 path[i]/path[0] = 窗内 d0 收盘 → di 收盘的真实(含送转/分红)累计收益。
    返回序列长度与输入一致。涨幅/回撤/CAGR 都改吃这条路径(不复权 close 在拆股票上会算错)。
    """
    if not pct_chg:
        raise ValueError("adjusted_path 需非空 pct_chg")
    path = [1.0]
    for r in pct_chg[1:]:
        path.append(path[-1] * (1.0 + r / 100.0))
    return path


def interval_return(close: list[float]) -> float:
    """区间涨幅(分数):close_end / close_start − 1。"""
    if len(close) < 2 or close[0] == 0:
        raise ValueError("interval_return 需 ≥2 个、且起点价非零")
    return close[-1] / close[0] - 1.0


def max_drawdown(close: list[float]) -> float:
    """最大回撤(分数):max_t(1 − close_t / 截至 t 的峰值)。"""
    if not close:
        raise ValueError("max_drawdown 需非空序列")
    peak = close[0]
    mdd = 0.0
    for c in close:
        peak = max(peak, c)
        if peak > 0:
            mdd = max(mdd, 1.0 - c / peak)
    return mdd


def annual_volatility(pct_chg: list[float], *, ddof: int = 1) -> float:
    """年化波动率(分数):std(pct_chg ÷ 100, ddof=1) × √252。pct_chg 为 tushare %-值。"""
    rets = np.asarray(pct_chg, dtype=float) / 100.0
    if rets.size - ddof <= 0:
        raise ValueError("annual_volatility 样本不足")
    return float(np.std(rets, ddof=ddof) * np.sqrt(_TRADING_DAYS))


def correlation(
    dates_a: list[str], pct_a: list[float], dates_b: list[str], pct_b: list[float]
) -> float:
    """两序列日收益相关性:按 trade_date 内连接对齐后 Pearson(pct_chg)。pct_chg 用 tushare %-值(相关性 scale 无关)。"""
    ma = dict(zip(dates_a, pct_a))
    mb = dict(zip(dates_b, pct_b))
    common = sorted(set(ma) & set(mb))
    if len(common) < 2:
        raise ValueError("correlation 需 ≥2 个共同交易日")
    a = np.array([ma[d] for d in common], dtype=float)
    b = np.array([mb[d] for d in common], dtype=float)
    if np.std(a) == 0 or np.std(b) == 0:
        raise ValueError("correlation 某序列零方差")
    return float(np.corrcoef(a, b)[0, 1])


def cagr(values: list[float], years: float) -> float:
    """复合年增速(分数):(末 / 首)^(1 / 年数) − 1。首期须为正。"""
    if len(values) < 2 or values[0] <= 0 or years <= 0:
        raise ValueError("cagr 需 ≥2 期、首期为正、年数为正")
    return (values[-1] / values[0]) ** (1.0 / years) - 1.0


def pe_percentile(history: list[float], current: float) -> float:
    """PE 历史分位(分数 ∈ [0,1]):count(历史 < 当前) / n,不插值。"""
    if not history:
        raise ValueError("pe_percentile 需非空历史")
    return sum(1 for h in history if h < current) / len(history)


__all__ = [
    "interval_return",
    "max_drawdown",
    "annual_volatility",
    "correlation",
    "cagr",
    "pe_percentile",
]
