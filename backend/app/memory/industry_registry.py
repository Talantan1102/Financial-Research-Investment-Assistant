"""Industry 实体归一 — 接申万行业分类(spec 原留 v1.x,2026-06-09 提前接)。

为什么:对话流记忆评估写侧根因——`registry.normalize_entity` 对 Industry 是 passthrough,
用户口里的「白酒 / 白酒Ⅱ / 高端白酒」落成不同 target 节点,观点演化(看多→中性)因此
分散在多个节点、互不作废,bi-temporal 链断开。归一到同一申万 canonical 才能修。

设计(最小化、可降级):
- canonical = 申万二级行业正式名(如「白酒Ⅱ」),与既有断言候选表对齐。
- 自由文本(高端白酒/次高端)→ canonical:先 alias 精确表,再 contains 模糊兜底。
- 申万全集:优先 Tushare `index_classify(src='SW2021', level='L2')` 拉取并缓存;
  无 token / 网络不可用时降级到内置 `_SW_L2_SEED`(覆盖评估与常见行业,够用)。
- 认不出的行业:passthrough + audit_flag=True(留痕,不强行编)。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# 内置申万二级种子(canonical 正式名)——无 Tushare 时的降级全集,也是 alias 的归宿。
# 评估脚本涉及 + A 股常见。Tushare 可用时会并入更全的官方列表。
_SW_L2_SEED: set[str] = {
    "白酒Ⅱ",
    "医药生物",
    "银行",
    "证券Ⅱ",
    "电力设备",
    "光伏设备",
    "通信设备",
    "半导体",
    "汽车整车",
    "食品加工",
    "饮料乳品",
    "煤炭开采",
    "房地产开发",
    "保险Ⅱ",
}

# 自由文本 alias → 申万 canonical。键统一小写去空白后比较。
_ALIAS: dict[str, str] = {
    "白酒": "白酒Ⅱ",
    "白酒ii": "白酒Ⅱ",
    "高端白酒": "白酒Ⅱ",
    "次高端白酒": "白酒Ⅱ",
    "次高端": "白酒Ⅱ",
    "医药": "医药生物",
    "医药行业": "医药生物",
    "生物医药": "医药生物",
    "创新药": "医药生物",
    "银行股": "银行",
    "光模块": "通信设备",
    "光通信": "通信设备",
    "cpo": "通信设备",
    "光伏": "光伏设备",
    "组件": "光伏设备",
    "逆变器": "电力设备",
    "储能": "电力设备",
    "新能源车": "汽车整车",
    "半导体设备": "半导体",
    "芯片": "半导体",
    "券商": "证券Ⅱ",
}

# contains 模糊兜底:label 含某 canonical 的核心词根 → 归该 canonical。
# 仅放歧义低的词根,避免误并(如「白酒」词根独属白酒Ⅱ)。
_CONTAINS_ROOTS: list[tuple[str, str]] = [
    ("白酒", "白酒Ⅱ"),
    ("医药", "医药生物"),
    ("光模块", "通信设备"),
    ("半导体", "半导体"),
    ("银行", "银行"),
    ("证券", "证券Ⅱ"),
    ("保险", "保险Ⅱ"),
    ("煤炭", "煤炭开采"),
]

# Tushare 拉取的全集缓存(进程级);None = 尚未尝试加载。
_sw_full: set[str] | None = None


def _key(label: str) -> str:
    return label.strip().lower().replace(" ", "")


def _load_shenwan_full() -> set[str]:
    """优先 Tushare index_classify(SW2021 L2)拉申万二级全集,失败降级到内置种子。

    进程级缓存一次。Tushare 不可用(无 token / 网络 / 包缺)→ 静默降级,不报错。
    """
    global _sw_full
    if _sw_full is not None:
        return _sw_full
    names = set(_SW_L2_SEED)
    try:
        from app.data.tushare_client import TushareClient

        api = TushareClient().get_api()
        if api is not None:
            df = api.index_classify(src="SW2021", level="L2")
            col = "industry_name" if "industry_name" in df.columns else "name"
            names |= {str(n).strip() for n in df[col] if str(n).strip()}
            logger.info("industry_registry: 申万二级从 Tushare 加载 %d 个", len(names))
    except Exception as exc:  # noqa: BLE001 — 降级到种子,不阻塞
        logger.info("industry_registry: Tushare 不可用,用内置申万种子降级: %s", exc)
    _sw_full = names
    return _sw_full


def normalize_industry(raw_label: str) -> tuple[str, bool]:
    """自由文本行业标签 → (申万 canonical, audit_flag)。

    归一顺序:① 直命中申万正式名 → 干净;② alias 精确表 → 干净;
    ③ contains 词根模糊 → 干净;④ 都不中 → passthrough + audit_flag=True。
    """
    label = (raw_label or "").strip()
    if not label:
        return label, True

    full = _load_shenwan_full()
    # ① 直命中申万正式名(忽略大小写/空白与 Ⅱ↔II 写法差异)
    norm_label = label.replace("II", "Ⅱ").replace("ii", "Ⅱ")
    for name in full:
        if _key(name) == _key(norm_label):
            return name, False

    # ② alias 精确表
    canon = _ALIAS.get(_key(label))
    if canon is not None:
        return canon, False

    # ③ contains 词根模糊兜底
    for root, target in _CONTAINS_ROOTS:
        if root in label:
            return target, False

    # ④ 认不出:留痕,不强行编
    return label, True
