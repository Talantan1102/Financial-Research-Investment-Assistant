"""L0 — cross_turn_grouper 算法深度补丁 #4 单元测试."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.memory.cross_turn_grouper import (
    DialogueChunk,
    build_sliding_window,
    group_episodes,
)
from app.memory.models import ChatMemoryEpisode

pytestmark = pytest.mark.unit


def _ep(idx: int, ts: datetime, user_msg: str, agent_msg: str = "") -> ChatMemoryEpisode:
    """Test helper: 构造 ChatMemoryEpisode (L0 不入库, 仅内存对象)."""
    return ChatMemoryEpisode(
        episode_id=uuid4(),
        user_id=uuid4(),
        session_id=uuid4(),
        episode_index=idx,
        user_message_text=user_msg,
        agent_response_text=agent_msg,
        source_kind="chat_turn",
        created_at=ts,
    )


def test_temporal_continuity_under_5min_merges_into_one_chunk() -> None:
    """相邻 episode 时间间隔 < 5min → 同 chunk."""
    base = datetime(2026, 5, 11, 10, 0, 0, tzinfo=UTC)
    eps = [
        _ep(0, base, "我刚买了股票"),
        _ep(1, base + timedelta(minutes=2), "茅台"),
        _ep(2, base + timedelta(minutes=4), "500 股"),
    ]
    chunks = group_episodes(eps)
    assert len(chunks) == 1
    assert len(chunks[0].episodes) == 3


def test_temporal_gap_over_5min_splits() -> None:
    """间隔 >= 5min → 切 chunk."""
    base = datetime(2026, 5, 11, 10, 0, 0, tzinfo=UTC)
    eps = [
        _ep(0, base, "你好"),
        _ep(1, base + timedelta(minutes=10), "茅台估值贵不贵"),
    ]
    chunks = group_episodes(eps)
    assert len(chunks) == 2


def test_keyword_coreference_merges_even_at_boundary() -> None:
    """共指 ts_code 即使时间稍长 (<10min) 也合并 — 关键词优先."""
    base = datetime(2026, 5, 11, 10, 0, 0, tzinfo=UTC)
    eps = [
        _ep(0, base, "我看好 600519"),
        _ep(1, base + timedelta(minutes=6), "600519 的护城河"),
    ]
    chunks = group_episodes(eps)
    assert len(chunks) == 1


def test_no_coreference_no_continuity_splits() -> None:
    """无共指 + 时间断 → 切."""
    base = datetime(2026, 5, 11, 10, 0, 0, tzinfo=UTC)
    eps = [
        _ep(0, base, "你好"),
        _ep(1, base + timedelta(minutes=15), "今天大盘走势"),
    ]
    chunks = group_episodes(eps)
    assert len(chunks) == 2


def test_sliding_window_truncates_to_5_turn() -> None:
    """build_sliding_window 截最近 5 turn (7 turn chunk → 取末 5)."""
    base = datetime(2026, 5, 11, 10, 0, 0, tzinfo=UTC)
    chunk_eps = [
        _ep(i, base + timedelta(seconds=30 * i), f"msg-{i}", f"agent-{i}") for i in range(7)
    ]
    chunk = DialogueChunk(episodes=chunk_eps)
    window = build_sliding_window(chunk, window=5)
    assert len(window) == 5
    # 末 5 turn 是 idx 2-6
    assert [t["episode_index"] for t in window] == [2, 3, 4, 5, 6]
    # 每 turn 含 user_message + agent_response 字段
    assert all("user_message" in t and "agent_response" in t for t in window)


def test_sliding_window_under_5_turn_returns_all() -> None:
    """少于 5 turn 全返回."""
    base = datetime(2026, 5, 11, 10, 0, 0, tzinfo=UTC)
    chunk_eps = [_ep(i, base + timedelta(seconds=30 * i), f"msg-{i}") for i in range(3)]
    chunk = DialogueChunk(episodes=chunk_eps)
    window = build_sliding_window(chunk, window=5)
    assert len(window) == 3


def test_empty_episodes_returns_empty_chunks() -> None:
    """空 list 输入 → 空 chunks 输出 (不抛)."""
    assert group_episodes([]) == []


def test_chunk_keywords_collects_ts_code_and_industry() -> None:
    """DialogueChunk.keywords() 收集 chunk 内所有关键词."""
    base = datetime(2026, 5, 11, 10, 0, 0, tzinfo=UTC)
    eps = [
        _ep(0, base, "茅台 600519 估值"),
        _ep(1, base + timedelta(minutes=1), "新能源 看好"),
    ]
    chunk = DialogueChunk(episodes=eps)
    kws = chunk.keywords()
    assert "600519" in kws
    assert "茅台" in kws
    assert "新能源" in kws
