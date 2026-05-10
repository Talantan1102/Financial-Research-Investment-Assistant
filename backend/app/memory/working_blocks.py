"""Tier 1 Working Memory — pure function layer for append / replace / paging.

spec ref: § 7 Working memory budget
contract ref: § 6 core_memory_append/replace 约束

设计要点:
- approx_token_count: 跟 PR #39 in_session_memory 同 calibration(中文 1.33 tokens/char)
- do_append_with_paging: MemGPT 哲学 — 超 budget 不报错, 踢 oldest lines
  Plan 1B: 仅返回被踢的 lines, 实际 archive 进 graph 由 HierarchicalMemory
  调 archival_memory_insert(stub by Plan 2 ship, 暂用 logger warn)
- do_replace_exact: substring exact match(不模糊), Python str.replace 行为
  不存在则 raise ValueError(防 silent miss)

注: 这层是纯函数, 跟 DB / DI 解耦. HierarchicalMemory.core_memory_append
用 PG repository 包装 + 调本层.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# === 常量 ===

BLOCK_DEFAULTS: dict[str, int] = {
    "persona": 500,  # spec § 7
    "scratchpad": 1000,  # spec § 7
}

APPEND_MAX_CHARS: int = 200  # 契约 § 6 防 spam

# 中文 token calibration(参考 v0.7 in-session memory)
_APPROX_CHARS_PER_TOKEN: float = 2.5


def approx_token_count(text: str) -> int:
    """Approximate token count(中文 1.33 tokens/char fallback)."""
    if not text:
        return 0
    return int(len(text) / _APPROX_CHARS_PER_TOKEN)


def do_append_with_paging(
    existing: str,
    new: str,
    max_tokens: int,
) -> tuple[str, list[str]]:
    """Append `new` to `existing`. Auto-page oldest lines if exceed max_tokens.

    Returns (new_content, paged_out_lines).

    Raises:
        ValueError: 如果 new 超 APPEND_MAX_CHARS.

    哲学:
    - MemGPT-style: 不报错, 踢 oldest lines
    - paged_out_lines 由调用层 archive 进 graph(Plan 2 ship 后实际归档,
      Plan 1B 阶段调用层只 logger.warning)
    """
    if len(new) > APPEND_MAX_CHARS:
        raise ValueError(
            f"core_memory_append content 超 {APPEND_MAX_CHARS} chars "
            f"(actual {len(new)}); use archival_memory_insert for longer facts"
        )

    candidate = new if not existing else f"{existing}\n{new}"

    if approx_token_count(candidate) <= max_tokens:
        return candidate, []

    # 超 budget — 按 line 切, 从前往后踢
    lines = candidate.split("\n")
    paged: list[str] = []
    while lines and approx_token_count("\n".join(lines)) > max_tokens:
        paged.append(lines.pop(0))

    if not lines:
        # 极端 case: 单行 new 都超 budget — 不再继续踢, 保留 new
        # 调用层应该 raise(因为这是异常配置), Plan 1B 暂时返回 new 原文 + 空 lines paged
        logger.warning(
            "core_memory_append: single line exceeds max_tokens=%d, returning anyway",
            max_tokens,
        )
        return new, paged

    return "\n".join(lines), paged


def do_replace_exact(
    existing: str,
    old_content: str,
    new_content: str,
) -> str:
    """Replace all occurrences of old_content with new_content.

    Raises:
        ValueError: old_content not found in existing.

    类比: Edit tool 的 replace_all 默认 false, 但 spec § 6 / 契约 § 6 没有
    显式说要不要 replace_all, 取折中: 替换所有出现(类似 Python str.replace),
    简洁安全.
    """
    if old_content not in existing:
        raise ValueError(
            f"core_memory_replace: old_content not found in block (old_len={len(old_content)})"
        )
    return existing.replace(old_content, new_content)
