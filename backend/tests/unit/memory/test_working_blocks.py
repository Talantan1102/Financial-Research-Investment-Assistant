"""L0: Working blocks 纯函数 — token counter + paging logic."""

from __future__ import annotations

import pytest
from app.memory.working_blocks import (
    APPEND_MAX_CHARS,
    BLOCK_DEFAULTS,
    approx_token_count,
    do_append_with_paging,
    do_replace_exact,
)

# ---- approx_token_count ----


def test_approx_token_count_chinese() -> None:
    """中文按 1.33 tokens/char(spec § 7 calibration)."""
    n = approx_token_count("茅台 600519")
    assert n > 0
    assert isinstance(n, int)


def test_approx_token_count_empty_zero() -> None:
    assert approx_token_count("") == 0


# ---- BLOCK_DEFAULTS ----


def test_block_defaults_persona_500() -> None:
    assert BLOCK_DEFAULTS["persona"] == 500


def test_block_defaults_scratchpad_1000() -> None:
    assert BLOCK_DEFAULTS["scratchpad"] == 1000


# ---- do_append_with_paging ----


def test_append_below_budget_no_paging() -> None:
    """budget 充裕 → 直接 append, paged_lines 空."""
    new_content, paged = do_append_with_paging(
        existing="line1\nline2",
        new="line3",
        max_tokens=500,
    )
    assert new_content == "line1\nline2\nline3"
    assert paged == []


def test_append_exceed_budget_pages_oldest_lines() -> None:
    """超 budget → 自动 paging oldest lines(MemGPT 哲学, 不报错)."""
    existing = "\n".join([f"line{i}" * 30 for i in range(20)])  # 大块文本
    new_content, paged = do_append_with_paging(
        existing=existing,
        new="newest_line",
        max_tokens=10,  # 故意小让必须 page
    )
    # paged 必非空(oldest 被踢)
    assert len(paged) > 0
    # newest_line 必在 new_content 末尾
    assert new_content.endswith("newest_line")


def test_append_max_chars_per_call_constraint() -> None:
    """APPEND_MAX_CHARS=200 — content 超 200 chars raise ValueError."""
    assert APPEND_MAX_CHARS == 200
    with pytest.raises(ValueError, match="200 chars"):
        do_append_with_paging(
            existing="",
            new="x" * 201,
            max_tokens=500,
        )


# ---- do_replace_exact ----


def test_replace_exact_match_succeeds() -> None:
    new = do_replace_exact(
        existing="cash flow 重要\nROE 重要",
        old_content="重要",
        new_content="关键",
    )
    # 注: replace_all 模式 — 替换所有 "重要" 为 "关键"
    assert "cash flow 关键" in new
    assert "ROE 关键" in new


def test_replace_no_match_raises() -> None:
    with pytest.raises(ValueError, match="not found"):
        do_replace_exact(
            existing="cash flow",
            old_content="不存在",
            new_content="新",
        )
