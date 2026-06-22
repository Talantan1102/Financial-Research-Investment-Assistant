"""中证800 成分股加载 + 清洗 → list[Stock]。

spec: docs/superpowers/specs/2026-06-22-eval-data-pipeline-design.md § ②
- 成分股取 index_weight(000906.SH, as_of 当月最近再平衡日)
- 补 name + sector via stock_basic (industry 列) — 一次批量拉取
- 过滤: ST/*ST、上市不满3年
- 返回清洗后 list[Stock]
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from eval.question_gen.stock_pool import Stock

_CSI800_CODE = "000906.SH"
# index_weight 只在月末再平衡日发布，查近 45 天区间可覆盖跨两个月的空窗
_INDEX_WEIGHT_LOOKBACK_DAYS = 45


def _parse_date(s: str) -> datetime:
    return datetime.strptime(s, "%Y%m%d")


def _is_st(name: str) -> bool:
    """ST / *ST / 退市"""
    return "ST" in name or "退" in name


def _listed_lt_3y(list_date: str | None, as_of: str) -> bool:
    """上市不满3年 → True (3y内不可算3y回撤)"""
    if not list_date:
        return True  # 保守过滤
    try:
        ld = _parse_date(str(list_date))
        aof = _parse_date(as_of)
    except ValueError:
        return True
    # 3 年 = 1095 天(保守)
    return (aof - ld).days < 365 * 3


async def load_csi800(tushare: Any, as_of: str) -> list[Stock]:
    """加载中证800成分股并清洗。

    Args:
        tushare: TushareService (Protocol)
        as_of: YYYYMMDD 日期字符串 (e.g. "20260612")

    Returns:
        清洗后的 list[Stock]，sector 来自 stock_basic industry 列
    """
    # 1. 取 index_weight (成分股)
    # Bug fix #1: tushare index_weight 只在月末再平衡日发布；直接传 as_of 可能返回 0 行。
    # 改为查 [as_of - 45天, as_of] 区间，再取区间内 trade_date 最大的一批行。
    as_of_dt = _parse_date(as_of)
    start_dt = as_of_dt - timedelta(days=_INDEX_WEIGHT_LOOKBACK_DAYS)
    start_date = start_dt.strftime("%Y%m%d")

    iw_df = await tushare.get_index_weight(
        index_code=_CSI800_CODE,
        start_date=start_date,
        end_date=as_of,
    )
    if iw_df.empty or "con_code" not in iw_df.columns:
        return []

    # 取区间内最新一次再平衡日的成分股
    if "trade_date" in iw_df.columns:
        latest_td = iw_df["trade_date"].max()
        iw_df = iw_df[iw_df["trade_date"] == latest_td]

    con_codes = iw_df["con_code"].dropna().unique().tolist()
    if not con_codes:
        return []

    # 2. Bug fix #2: 一次性批量拉取所有在市股票基本信息，避免 800 次单股调用
    # get_stock_basic(ts_code=None) → list_status="L" 全量拉取
    basic_all = await tushare.get_stock_basic()
    if basic_all.empty:
        return []

    # 构建 ts_code → row 的查找字典
    basic_lookup: dict[str, Any] = {}
    for _, row in basic_all.iterrows():
        code = str(row.get("ts_code", ""))
        if code:
            basic_lookup[code] = row

    # 3. 对每只成分股查找基本信息 + 过滤
    stocks: list[Stock] = []
    for ts_code in con_codes:
        row = basic_lookup.get(ts_code)
        if row is None:
            continue
        name = str(row.get("name", ts_code))
        industry = str(row.get("industry", "其他"))
        list_date_val = row.get("list_date", None)

        # 过滤
        if _is_st(name):
            continue
        if _listed_lt_3y(list_date_val, as_of):
            continue

        stocks.append(Stock(ts_code=ts_code, name=name, sector=industry))

    return stocks
