"""抽取后校验护栏 — prompt/解码漏网的硬兜底:幻觉日期、脏 label。

对话流评估写侧根因之一:弱模型即便给了日期纪律仍可能编 valid_to(2027-04-01、
"假设2025-04-15"),或把整句"看多高端白酒"当 entity_label。这一层在边入库前做
确定性兜底,不依赖模型遵从。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

# 整句谓词短语(脏实体)的常见起头——entity_label 不该是这些
_STANCE_PREFIXES = (
    "看多",
    "看空",
    "看好",
    "看淡",
    "看衰",
    "买入",
    "卖出",
    "加仓",
    "减仓",
    "持有",
    "清仓",
    "建仓",
)


def is_stance_phrase_label(label: str) -> bool:
    """label 是不是整句谓词短语(脏实体),而非名词性实体。"""
    s = (label or "").strip()
    return any(s.startswith(p) for p in _STANCE_PREFIXES)


def _parse_iso(v: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def sanitize_edge(
    edge: dict[str, Any],
    *,
    episode_date: datetime,
    window_days: int = 400,
) -> dict[str, Any]:
    """把越界/不可解析的幻觉 valid_to 重置为 null。

    valid_to 合理区间 = [episode_date - window_days, episode_date + 1 天]:
    观点的结束日不该在对话日之后(未来),也不该早得离谱(超 window)。越界或
    解析失败 → null(等价于"观点仍有效/无明确结束"),不让幻觉日期落库。
    """
    out = dict(edge)
    vt = out.get("valid_to")
    if not vt:
        return out
    dt = _parse_iso(vt)
    if dt is None:
        out["valid_to"] = None
        return out
    # 对齐时区,避免 naive/aware 比较报错
    ep = episode_date if episode_date.tzinfo else episode_date.replace(tzinfo=dt.tzinfo)
    if dt.tzinfo is None and ep.tzinfo is not None:
        dt = dt.replace(tzinfo=ep.tzinfo)
    lo = ep - timedelta(days=window_days)
    hi = ep + timedelta(days=1)
    if dt < lo or dt > hi:
        out["valid_to"] = None
    return out
