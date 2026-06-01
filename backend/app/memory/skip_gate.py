"""Skip-extraction gate(spec § 4 优化 #3).

LLM call 前过 heuristic, 节省单 session 成本(skip 50% chitchat / 已抽 / 短消息):
  - episode 长度 < 50 字符 → skip
  - 无 ts_code / metric / strategy 关键词 → skip
  - extracted_at IS NOT NULL → skip(防重)

Plan 2 extractor + Plan 5 batch_extractor 都调用. 契约 § 5 函数签名.
"""

from __future__ import annotations

from app.memory.models import ChatMemoryEpisode
from app.memory.registry import SEARCH_TS_CODE_RE as _TS_CODE_RE  # C64: SSOT in registry

# metric 关键词(对齐 spec 附录 A 白名单 + 中文常用)
_METRIC_KEYWORDS: frozenset[str] = frozenset(
    {
        "ROE",
        "ROA",
        "PE",
        "PB",
        "EPS",
        "净利润",
        "营收",
        "毛利率",
        "净利率",
        "现金流",
        "负债率",
        "市盈率",
        "市净率",
        "估值",
        "增速",
        "指标",
        "财务",
    }
)

# strategy 关键词
_STRATEGY_KEYWORDS: frozenset[str] = frozenset(
    {
        "价值投资",
        "成长投资",
        "动量",
        "趋势",
        "套利",
        "长期持有",
        "短线",
        "中线",
        "网格",
        "定投",
        "策略",
        "偏好",
        "看好",
        "看空",
        "持仓",
        "加仓",
        "减仓",
        "卖出",
        "买入",
        "止损",
        "止盈",
    }
)

_MIN_LENGTH = 50


def _has_relevant_keyword(text: str) -> bool:
    """Returns True iff text contains any ts_code / metric / strategy keyword."""
    if _TS_CODE_RE.search(text):
        return True
    if any(kw in text for kw in _METRIC_KEYWORDS):
        return True
    return any(kw in text for kw in _STRATEGY_KEYWORDS)


def should_skip_extraction(episode: ChatMemoryEpisode) -> tuple[bool, str]:
    """Returns (skip, reason).

    spec § 4 优化 #3:
      - 已 extracted_at 不为 NULL → skip(防重) — 优先判断, 不用读 text
      - 含 ts_code / metric / strategy 关键词 → 不 skip(关键词命中视为高信号, 即便短)
      - episode 总长度 < 50 字符且无关键词 → skip
      - 长度 ≥ 50 但无关键词 → skip(no_relevant_keyword)
      - 否则 → (False, "")

    设计取舍: 关键词命中优先于长度门, 因 "卖光茅台 600519.SH" 短但金融语义满载,
    不该被 length 门 false-skip; 反之 50+ 字闲聊该 skip.
    Plan 2 extractor / Plan 5 batch_extractor 都调用此函数.
    """
    if episode.extracted_at is not None:
        return True, "already_extracted"

    user_text = episode.user_message_text or ""
    agent_text = episode.agent_response_text or ""
    text = (user_text + " " + agent_text).strip()

    if _has_relevant_keyword(text):
        return False, ""

    if len(text) < _MIN_LENGTH:
        return True, f"length<{_MIN_LENGTH}"

    return True, "no_relevant_keyword"
