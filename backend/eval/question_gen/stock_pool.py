"""手挑股票池：15 只确定性种子股，按板块组织。

供 question_gen 评估流程引用。纯静态数据 + 纯函数查询，不依赖网络/DB/LLM。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Stock:
    ts_code: str
    name: str
    sector: str


POOL: tuple[Stock, ...] = (
    # 白酒
    Stock("600519.SH", "贵州茅台", "白酒"),
    Stock("000858.SZ", "五粮液", "白酒"),
    Stock("000568.SZ", "泸州老窖", "白酒"),
    Stock("002304.SZ", "洋河股份", "白酒"),
    Stock("000596.SZ", "古井贡酒", "白酒"),
    # 银行
    Stock("600036.SH", "招商银行", "银行"),
    Stock("601398.SH", "工商银行", "银行"),
    Stock("000001.SZ", "平安银行", "银行"),
    # 新能源(原比亚迪 002594 近三年有 1拆N 送转,不复权口径下回撤/涨幅失真 → 换成非拆股的隆基绿能)
    Stock("601012.SH", "隆基绿能", "新能源"),
    Stock("300750.SZ", "宁德时代", "新能源"),
    Stock("002460.SZ", "赣锋锂业", "新能源"),
    # 医药
    Stock("600276.SH", "恒瑞医药", "医药"),
    Stock("300760.SZ", "迈瑞医疗", "医药"),
    # 电子
    Stock("002475.SZ", "立讯精密", "电子"),
    Stock("000725.SZ", "京东方A", "电子"),
)


def by_sector(pool: tuple[Stock, ...] = POOL) -> dict[str, list[Stock]]:
    """返回 sector -> [Stock, ...] 映射，保持 pool 中的出现顺序。

    pool 参数默认为全局 POOL，可注入子集以支持参数化测试。
    """
    result: dict[str, list[Stock]] = {}
    for stock in pool:
        result.setdefault(stock.sector, []).append(stock)
    return result


def sectors_with_at_least(n: int, pool: tuple[Stock, ...] = POOL) -> list[str]:
    """返回成员数 >= n 的板块名，按板块名排序（稳定）。"""
    grouped = by_sector(pool)
    return sorted(sector for sector, stocks in grouped.items() if len(stocks) >= n)


def get(ts_code: str) -> Stock:
    """按 ts_code 查找股票，找不到 raise KeyError。"""
    for stock in POOL:
        if stock.ts_code == ts_code:
            return stock
    raise KeyError(ts_code)
