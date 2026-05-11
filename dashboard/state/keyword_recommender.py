"""相关推荐 keyword fallback — sum-of-keyword-length 评分。spec § 6.3。

沿用 `classify_layer` 同款评分:命中 token 越长得分越高。Milvus 不可用时退化路径。
"""

from __future__ import annotations

import re

from dashboard.derive.deep_card_types import DeepCard

TOKEN_RE = re.compile(r"[A-Za-z][\w-]+|[一-龥]+")


def _tokens(card: DeepCard) -> list[str]:
    """从 DeepCard 文本字段抽 keyword token(简单切词,中英文混合)。"""
    parts: list[str] = []
    for f in ("what", "why", "tradeoff", "lessons_learned"):
        v = getattr(card, f, None)
        if isinstance(v, str):
            parts.append(v)
    for a in card.alternatives:
        parts.append(a.name)
        parts.append(a.brief_tradeoff)
    if card.chosen_alternative:
        parts.append(card.chosen_alternative)
    text = " ".join(parts)
    return [t for t in TOKEN_RE.findall(text) if len(t) >= 2]


def recommend_by_keyword(
    pivot: DeepCard, all_cards: list[DeepCard], *, k: int = 5
) -> list[DeepCard]:
    """对 pivot 与每张 card 算 keyword 命中得分,返回 top-k(排除 self)。

    评分:Σ len(token) for token in (pivot_tokens ∩ card_tokens)。
    """
    pivot_tokens = set(_tokens(pivot))
    if not pivot_tokens:
        return []
    scored: list[tuple[DeepCard, int]] = []
    for c in all_cards:
        if c.cap_id == pivot.cap_id:
            continue
        c_tokens = set(_tokens(c))
        common = pivot_tokens & c_tokens
        if not common:
            continue
        score = sum(len(t) for t in common)
        scored.append((c, score))
    scored.sort(key=lambda kv: kv[1], reverse=True)
    return [c for c, _ in scored[:k]]
