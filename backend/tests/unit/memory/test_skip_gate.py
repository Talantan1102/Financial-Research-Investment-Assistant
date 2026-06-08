"""L0 — skip_gate.should_skip_extraction(spec § 4 优化 #3).

契约 § 5 函数签名: should_skip_extraction(episode) -> tuple[bool, str].
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.memory.models import ChatMemoryEpisode
from app.memory.skip_gate import should_skip_extraction


def _make_episode(
    *,
    user_message: str = "我加仓了贵州茅台 600519.SH 500 股",
    agent_response: str = "好的,已记录持仓变化",
    extracted_at: datetime | None = None,
) -> ChatMemoryEpisode:
    return ChatMemoryEpisode(
        episode_id=uuid4(),
        user_id=uuid4(),
        session_id=uuid4(),
        episode_index=0,
        user_message_text=user_message,
        agent_response_text=agent_response,
        source_kind="chat_turn",
        extracted_at=extracted_at,
    )


def test_long_episode_with_ts_code_not_skipped() -> None:
    ep = _make_episode()
    skip, reason = should_skip_extraction(ep)
    assert skip is False
    assert reason == ""


def test_short_episode_skipped() -> None:
    """spec § 4: episode < 50 字 → skip."""
    ep = _make_episode(user_message="嗯", agent_response="好的")
    skip, reason = should_skip_extraction(ep)
    assert skip is True
    assert "length" in reason.lower() or "短" in reason


def test_no_keyword_skipped() -> None:
    """无 ts_code / metric / strategy 关键词 → skip."""
    long_chitchat = (
        "今天天气不错,我吃了个汉堡,然后去散步了一会,回来准备看会儿剧下午可能会去公园逛逛,晚上吃面"
    )
    ep = _make_episode(user_message=long_chitchat, agent_response="听起来不错")
    skip, reason = should_skip_extraction(ep)
    assert skip is True
    assert "keyword" in reason.lower() or "关键词" in reason


def test_already_extracted_skipped() -> None:
    """extracted_at IS NOT NULL → skip(防重)."""
    ep = _make_episode(extracted_at=datetime.now(UTC))
    skip, reason = should_skip_extraction(ep)
    assert skip is True
    assert "extracted" in reason.lower() or "已抽" in reason


def test_metric_keyword_only_not_skipped() -> None:
    """ROE / 净利润 / PE 这类 metric 关键词命中 → 不 skip."""
    ep = _make_episode(
        user_message="我比较看重 ROE 和净利润增速这两个指标对未来判断很关键",
        agent_response="ok",
    )
    skip, _ = should_skip_extraction(ep)
    assert skip is False


def test_strategy_keyword_only_not_skipped() -> None:
    """价值投资 / 动量 / 趋势 这类 strategy 关键词命中 → 不 skip."""
    ep = _make_episode(
        user_message="我偏好价值投资和长期持有的策略,一直如此坚持",
        agent_response="ok",
    )
    skip, _ = should_skip_extraction(ep)
    assert skip is False


# ---- C64 regression: SSOT for _TS_CODE_RE ----


def test_ts_code_embedded_in_free_text_not_skipped() -> None:
    """C64: skip_gate should detect ts_code embedded mid-sentence (word-boundary match).

    Verifies that the shared SEARCH_TS_CODE_RE (word-boundary) correctly triggers
    even when the ts_code is surrounded by other characters.
    """
    ep = _make_episode(
        user_message="看看 600519.SH 怎么样",
        agent_response="ok",
    )
    skip, _ = should_skip_extraction(ep)
    # ts_code in free text → high-signal → not skipped
    assert skip is False


def test_skip_gate_ts_code_re_is_registry_ssot() -> None:
    """C64: skip_gate._TS_CODE_RE must be the same object as registry.SEARCH_TS_CODE_RE.

    Single-owner check: only one definition of the search-variant regex.
    """
    from app.memory import skip_gate
    from app.memory.registry import SEARCH_TS_CODE_RE

    assert skip_gate._TS_CODE_RE is SEARCH_TS_CODE_RE


# === 对话流评估冒烟发现(2026-06-05):真实散户口语全军覆没 ===
# 散户说「看多/转中性/建仓/清了/割肉」而非白名单里的书面语「看好/持仓/卖出」,
# 导致有效 session 被静默跳过(skipped_reason=no_relevant_keyword)、0 边入库。
# 词源:.claude/skills/retail-investor-voice/references/corpus.md 黑话词典。


def _ep(text: str) -> ChatMemoryEpisode:
    return ChatMemoryEpisode(
        user_id=uuid4(),
        session_id=uuid4(),
        episode_index=1,
        user_message_text=text,
        agent_response_text="",
    )


def test_colloquial_stance_words_not_skipped() -> None:
    """散户口语观点表达不得被关键词门误杀。"""
    cases = [
        "我自己基本研究完了 结论就是高端白酒值得拿 起码三年 我就认提价权这一条",
        "看多我收回 转中性吧 不看空 但也犯不上再按原来那套拿着了",
        "那只新能源清了 换成沪深300指增了 这波操作我自己都服",
        "亏麻了 割肉还是死扛 兄弟给个准话啊 被套两个月了",
        "我上周建仓了一点 想抄底结果接了个飞刀 现在站岗呢",
    ]
    for text in cases:
        skip, reason = should_skip_extraction(_ep(text))
        assert not skip, f"口语被误杀: {text!r} (reason={reason})"
