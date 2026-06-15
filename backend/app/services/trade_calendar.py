"""确定性 A 股交易日历(mock / 离线用)。

绝不调 LLM、不读网络、不读墙上时钟:工作日规则 + 静态节假日表。覆盖年份外回退纯
工作日规则。节假日表 = 中国 A 股(沪深)休市日中落在周一-周五的那些(周末本就由
weekday 规则覆盖)。逐年需对官方交易日历校验更新;覆盖边界见 _HOLIDAYS 年份(2024-2026)。

real 路径走 tushare trade_cal API(见 RealTushareService.get_trade_cal);本模块只服务
mock/离线确定性场景,与 RL/验证集的"冻结 as-of + 可复现"诉求一致。
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

# A 股工作日休市日(YYYYMMDD)。只列落在周一-周五的法定休市日;周末由规则覆盖。
# 来源口径:沪深交易所每年公告的休市安排。覆盖 2024-2026,逐年校验更新。
_HOLIDAYS: set[str] = {
    # 2024
    "20240101",  # 元旦
    "20240209",  # 除夕(2024 春节首个休市日)
    "20240212",
    "20240213",
    "20240214",
    "20240215",
    "20240216",  # 春节
    "20240404",
    "20240405",  # 清明
    "20240501",
    "20240502",
    "20240503",  # 劳动节
    "20240610",  # 端午
    "20240916",
    "20240917",  # 中秋
    "20241001",
    "20241002",
    "20241003",
    "20241004",
    "20241007",  # 国庆
    # 2025
    "20250101",  # 元旦
    "20250128",
    "20250129",
    "20250130",
    "20250131",
    "20250203",
    "20250204",  # 春节
    "20250404",  # 清明
    "20250501",
    "20250502",
    "20250505",  # 劳动节
    "20250602",  # 端午
    "20251001",
    "20251002",
    "20251003",
    "20251006",
    "20251007",
    "20251008",  # 国庆+中秋
    # 2026
    "20260101",
    "20260102",  # 元旦
    "20260216",
    "20260217",
    "20260218",
    "20260219",
    "20260220",  # 春节
    "20260406",  # 清明
    "20260501",  # 劳动节
    "20260619",  # 端午
    "20260925",  # 中秋
    "20261001",
    "20261002",
    "20261005",
    "20261006",
    "20261007",
    "20261008",  # 国庆
}

_SEED_LOOKBACK_DAYS = 10  # 区间起点前回看几天补 pretrade_date 种子(覆盖最长节假日缺口)


def _is_open(d: date) -> bool:
    if d.weekday() >= 5:  # 5=周六 6=周日
        return False
    return d.strftime("%Y%m%d") not in _HOLIDAYS


def _parse(ymd: str) -> date:
    return date(int(ymd[:4]), int(ymd[4:6]), int(ymd[6:8]))


def build_calendar_df(start: str, end: str) -> pd.DataFrame:
    """返回 [start, end] 闭区间每日一行:cal_date / is_open(0/1) / pretrade_date。

    pretrade_date = 严格早于该 cal_date 的最近一个交易日(对齐 tushare 的"上一交易日"语义);
    区间起点前的最近交易日经 _SEED_LOOKBACK_DAYS 回看种子化,使首行 pretrade 也正确。
    """
    s, e = _parse(start), _parse(end)

    # 种子:区间起点前最近的交易日
    prev_open: str | None = None
    probe = s - timedelta(days=1)
    for _ in range(_SEED_LOOKBACK_DAYS):
        if _is_open(probe):
            prev_open = probe.strftime("%Y%m%d")
            break
        probe -= timedelta(days=1)

    rows: list[dict[str, object]] = []
    d = s
    while d <= e:
        ymd = d.strftime("%Y%m%d")
        is_open = _is_open(d)
        rows.append({"cal_date": ymd, "is_open": 1 if is_open else 0, "pretrade_date": prev_open})
        if is_open:
            prev_open = ymd
        d += timedelta(days=1)
    return pd.DataFrame(rows)
