"""v1.x A5a follow-up #1: 行业 DCF default 表 + tushare industry 字符串标准化。

设计要点 (spec § 6.4):
- 17 个常见行业的 WACC + terminal_growth 经验值 (post-dogfood calibrate);
  消费/品牌 7-7.5% / 科技成长 10-11% / 金融 8-9% / 周期 8.5-9% / 公用 7%。
- 行业字符串 normalize 用 substring match,容错 tushare stock_basic.industry 多种写法
  ('白酒制造' / '食品饮料' / '酒类' 都映射到 mapping table key)。
- 不命中 → '_default' (router 用 _default mapping 跑 PE + DCF 2 model)。

spec ref: 2026-05-16-v1.x-multi-valuation-cross-check-design.md § 6.4 + § 5
"""

from __future__ import annotations

__all__ = [
    "INDUSTRY_DCF_DEFAULTS",
    "get_industry_dcf_defaults",
    "normalize_industry",
]


# WACC / terminal growth 默认表 — INDUSTRY_VALUATION_MAPPING 同 key set。
INDUSTRY_DCF_DEFAULTS: dict[str, dict[str, float]] = {
    # 消费 / 品牌
    "白酒": {"wacc": 0.07, "terminal_growth": 0.025},
    "食品饮料": {"wacc": 0.07, "terminal_growth": 0.025},
    "家电": {"wacc": 0.07, "terminal_growth": 0.025},
    "服装": {"wacc": 0.075, "terminal_growth": 0.025},
    # 科技 / 成长
    "软件服务": {"wacc": 0.10, "terminal_growth": 0.030},
    "半导体": {"wacc": 0.11, "terminal_growth": 0.030},
    "互联网": {"wacc": 0.10, "terminal_growth": 0.030},
    # 金融
    "银行": {"wacc": 0.08, "terminal_growth": 0.020},
    "保险": {"wacc": 0.08, "terminal_growth": 0.020},
    "证券": {"wacc": 0.09, "terminal_growth": 0.020},
    # 地产 / 周期
    "房地产开发": {"wacc": 0.09, "terminal_growth": 0.020},
    "钢铁": {"wacc": 0.09, "terminal_growth": 0.020},
    "煤炭": {"wacc": 0.09, "terminal_growth": 0.020},
    "化工": {"wacc": 0.09, "terminal_growth": 0.020},
    # 重资本 / 公用
    "电信运营": {"wacc": 0.08, "terminal_growth": 0.025},
    "电力": {"wacc": 0.07, "terminal_growth": 0.020},
    "公用事业": {"wacc": 0.07, "terminal_growth": 0.020},
    # Fallback
    "_default": {"wacc": 0.085, "terminal_growth": 0.025},
}


# Tushare industry 字符串 → INDUSTRY_VALUATION_MAPPING key 的 substring 规则表。
# 关键字按"具体优先"顺序排列 (更长的关键字先匹配,如 '电信运营' 先于 '运营')。
_INDUSTRY_NORMALIZATION: tuple[tuple[str, str], ...] = (
    # 消费 / 品牌
    ("白酒", "白酒"),
    ("酒类", "白酒"),  # 啤酒 / 黄酒等 — 白酒 mapping 兼容
    ("食品", "食品饮料"),
    ("饮料", "食品饮料"),
    ("家电", "家电"),
    ("家用电器", "家电"),
    ("电器", "家电"),
    ("服装", "服装"),
    ("纺织", "服装"),
    ("服饰", "服装"),
    # 科技 / 成长
    ("软件", "软件服务"),
    ("互联网", "互联网"),
    ("半导体", "半导体"),
    ("集成电路", "半导体"),
    ("芯片", "半导体"),
    ("信息技术", "软件服务"),
    # 金融
    ("银行", "银行"),
    ("保险", "保险"),
    ("证券", "证券"),
    # 地产 / 周期
    ("房地产", "房地产开发"),
    ("地产", "房地产开发"),
    ("钢铁", "钢铁"),
    ("煤炭", "煤炭"),
    ("化工", "化工"),
    ("化学", "化工"),
    # 重资本 / 公用
    ("电信运营", "电信运营"),
    ("通信运营", "电信运营"),
    ("电力", "电力"),
    ("公用事业", "公用事业"),
    ("水务", "公用事业"),
    ("燃气", "公用事业"),
)


def normalize_industry(raw_industry: str | None) -> str:
    """Tushare industry 字符串 → INDUSTRY_VALUATION_MAPPING key。

    Substring 匹配 (更长 keyword 优先)。空 / None → '_default'。

    Args:
        raw_industry: tushare stock_basic.industry 原始字符串
            (例: '白酒', '食品饮料', '半导体', '银行' 等)

    Returns:
        normalized industry key,保证存在于 INDUSTRY_VALUATION_MAPPING +
        INDUSTRY_DCF_DEFAULTS 中。
    """
    if not raw_industry:
        return "_default"
    for keyword, key in _INDUSTRY_NORMALIZATION:
        if keyword in raw_industry:
            return key
    return "_default"


def get_industry_dcf_defaults(industry: str) -> tuple[float, float]:
    """查行业的 (wacc, terminal_growth) defaults。

    industry 应是 normalize_industry() 输出 (mapping key)。不命中 → _default。

    Returns:
        (wacc, terminal_growth) tuple。两数都是 decimal (0.07 = 7%)。
    """
    entry = INDUSTRY_DCF_DEFAULTS.get(industry, INDUSTRY_DCF_DEFAULTS["_default"])
    return entry["wacc"], entry["terminal_growth"]
