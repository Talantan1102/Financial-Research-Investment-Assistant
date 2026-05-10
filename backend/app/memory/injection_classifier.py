"""Algorithm 深度补丁 #2 — Memory 投毒 + Agent 幻觉写防御.

Plan 4 ship: minimal evidence_quote_in_episode + EvidenceNotFoundError.
Plan 5 ship: is_prompt_injection (rules + ML classifier).

Per shared contract § 17 A6:
    evidence_quote_in_episode minimal version (whitespace-tolerant substring) is
    shipped here by Plan 4. Plan 5 will Edit (NOT replace) this file to add
    is_prompt_injection.

Contracts § 5 spec ref.
"""

from __future__ import annotations

import re


class EvidenceNotFoundError(ValueError):
    """Agent 调 archival_memory_insert 时 evidence_quote 不在 episode 原文.

    Plan 4 在 archival_memory_insert MCP tool 内 raise; agent 必须改 evidence_quote
    重试. 继承 ValueError 保持调用方 except 兼容性.
    """


def evidence_quote_in_episode(quote: str, episode_text: str) -> bool:
    """Substring 校验 (空白容忍).

    去掉 quote / episode 中的所有连续空白(包括 \\n / \\t / 全角空格), 再做
    substring containment check.

    Examples:
        "买了 500 股" matches "买了500股"
        "我永不碰科技股" does NOT match "今天买了 500 股茅台"

    Returns:
        True iff normalized quote is a non-empty substring of normalized episode.
    """
    if not quote or not quote.strip():
        return False
    q_norm = re.sub(r"\s+", "", quote)
    e_norm = re.sub(r"\s+", "", episode_text or "")
    if not q_norm:
        return False
    return q_norm in e_norm
