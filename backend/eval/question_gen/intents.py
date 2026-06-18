"""题面模板层 —— 个股/配对研究意图的中文问题文案(纯字符串拼接,无依赖)。

spec: docs/superpowers/specs/2026-06-17-question-gen-mvp-design.md
operators 层给计算派发;本层只负责把"指标×股票×窗口"组装成自然语言题面。
入参 window_cn 已是中文(调用方传 legality.window_cn 的结果,如 "近一年"),模板直接拼。
"""

from __future__ import annotations

INTENT = "stock_study"

INTENT_SNAPSHOT = "snapshot_quote"

_SNAPSHOT_LABELS = {
    "PE": "市盈率(PE)",
    "PB": "市净率(PB)",
    "换手率": "换手率",
    "股息率": "股息率",
}

INTENT_FINANCIAL = "financial_report"

_FINANCIAL_RATIO_LABELS = {"ROE": "ROE", "资产负债率": "资产负债率", "毛利率": "销售毛利率"}
_FINANCIAL_AMOUNT_LABELS = {"营收": "营业收入", "净利": "净利润"}


def q_single(indicator: str, name: str, window_cn: str) -> str:
    """单股单指标题面;未知 indicator raise ValueError。

    涨幅/回撤/波动 按 window_cn 填窗口;CAGR 固定"最近三年"(需 >=2 年才有意义)。
    """
    if indicator == "涨幅":
        return f"{name}最近{window_cn}涨了多少?"
    if indicator == "回撤":
        return f"{name}最近{window_cn}的最大回撤是多少?"
    if indicator == "波动":
        return f"{name}最近{window_cn}的年化波动率是多少?"
    if indicator == "CAGR":
        return f"{name}最近三年的复合年化收益率(CAGR)是多少?"
    raise ValueError(f"未知指标:{indicator!r}")


def q_dual(name: str, window_cn: str) -> str:
    """单股双指标题面:回撤 + 波动一并问。"""
    return f"{name}最近{window_cn}的最大回撤和年化波动率分别是多少?"


def q_corr(name_a: str, name_b: str, window_cn: str) -> str:
    """两股日收益率相关性题面。"""
    return f"{name_a}和{name_b}最近{window_cn}的日收益率相关性是多少?"


def q_rank(sector: str, names: list[str], window_cn: str) -> str:
    """板块内多只排序题面:涨幅最高前三。"""
    joined = "、".join(names)
    return f"{sector}板块这几只({joined})里,最近{window_cn}涨幅最高的前三只是哪几只?"


def q_filter(names: list[str], window_cn: str) -> str:
    """多只多条件筛选题面:涨幅为正且最大回撤小于 20%。"""
    joined = "、".join(names)
    return f"{joined}这几只里,最近{window_cn}涨幅为正、且最大回撤小于20%的有哪几只?"


def q_snapshot(name: str, indicator: str, trade_date: str) -> str:
    """行情快照取数题面;trade_date 形如 "20260612" → "2026年06月12日"。未知指标 raise ValueError。"""
    label = _SNAPSHOT_LABELS.get(indicator)
    if label is None:
        raise ValueError(f"未知快照指标:{indicator!r}")
    d = f"{trade_date[:4]}年{trade_date[4:6]}月{trade_date[6:]}日"
    return f"{name}在{d}的{label}是多少?"


def q_financial(name: str, indicator: str, period_label: str) -> str:
    """财报取数题面。比率类问"是多少?"(%);金额类问"是多少亿元?"。未知指标 raise ValueError。"""
    if indicator in _FINANCIAL_RATIO_LABELS:
        return f"{name}{period_label}的{_FINANCIAL_RATIO_LABELS[indicator]}是多少?"
    if indicator in _FINANCIAL_AMOUNT_LABELS:
        return f"{name}{period_label}的{_FINANCIAL_AMOUNT_LABELS[indicator]}是多少亿元?"
    raise ValueError(f"未知财报指标:{indicator!r}")


INTENT_POSITION = "position_calc"


def q_position_value(name: str, qty: int, trade_date: str) -> str:
    """单仓市值题面。"""
    d = f"{trade_date[:4]}年{trade_date[4:6]}月{trade_date[6:]}日"
    return f"某账户持有{name}{qty}股,以{d}的收盘价计算,这笔持仓的市值是多少元?"


def q_position_pnl(name: str, qty: int, cost: float, trade_date: str) -> str:
    """单仓浮动盈亏题面。"""
    d = f"{trade_date[:4]}年{trade_date[4:6]}月{trade_date[6:]}日"
    return f"某账户持有{name}{qty}股、成本价{cost}元/股,以{d}的收盘价计算,这笔持仓的浮动盈亏是多少元?"


INTENT_PORTFOLIO = "portfolio_calc"


def q_portfolio_weight(basket_desc: str, target_name: str, trade_date: str) -> str:
    """组合权重题面;basket_desc 形如 "贵州茅台100股、五粮液200股"。"""
    d = f"{trade_date[:4]}年{trade_date[4:6]}月{trade_date[6:]}日"
    return f"某账户持有{basket_desc},以{d}的收盘价计算,{target_name}的持仓市值占整个组合的比例是百分之多少?"


def q_portfolio_hhi(basket_desc: str, trade_date: str) -> str:
    """组合 HHI 题面。"""
    d = f"{trade_date[:4]}年{trade_date[4:6]}月{trade_date[6:]}日"
    return f"某账户持有{basket_desc},以{d}的收盘价计算,该组合的持仓集中度指数HHI(各持仓市值权重的平方和)是多少?"


__all__ = [
    "INTENT",
    "INTENT_SNAPSHOT",
    "INTENT_FINANCIAL",
    "INTENT_POSITION",
    "INTENT_PORTFOLIO",
    "q_single",
    "q_dual",
    "q_corr",
    "q_rank",
    "q_filter",
    "q_snapshot",
    "q_financial",
    "q_position_value",
    "q_position_pnl",
    "q_portfolio_weight",
    "q_portfolio_hhi",
]
