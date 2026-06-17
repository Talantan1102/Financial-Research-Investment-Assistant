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
    # 新能源
    Stock("002594.SZ", "比亚迪", "新能源"),
    Stock("300750.SZ", "宁德时代", "新能源"),
    Stock("002460.SZ", "赣锋锂业", "新能源"),
    # 医药
    Stock("600276.SH", "恒瑞医药", "医药"),
    Stock("300760.SZ", "迈瑞医疗", "医药"),
    # 电子
    Stock("002475.SZ", "立讯精密", "电子"),
    Stock("000725.SZ", "京东方A", "电子"),
)


def by_sector() -> dict[str, list[Stock]]:
    """返回 sector -> [Stock, ...] 映射，保持 POOL 中的出现顺序。"""
    result: dict[str, list[Stock]] = {}
    for stock in POOL:
        result.setdefault(stock.sector, []).append(stock)
    return result


def sectors_with_at_least(n: int) -> list[str]:
    """返回成员数 >= n 的板块名，按板块名排序（稳定）。"""
    grouped = by_sector()
    return sorted(sector for sector, stocks in grouped.items() if len(stocks) >= n)


def get(ts_code: str) -> Stock:
    """按 ts_code 查找股票，找不到 raise KeyError。"""
    for stock in POOL:
        if stock.ts_code == ts_code:
            return stock
    raise KeyError(ts_code)
