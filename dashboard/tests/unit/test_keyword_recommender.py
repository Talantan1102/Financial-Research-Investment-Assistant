"""keyword 相关推荐 fallback — spec § 6.3。Plan 1 Task 8。"""

from __future__ import annotations

from dashboard.derive.deep_card_types import DeepCard
from dashboard.state.keyword_recommender import recommend_by_keyword


def test_recommend_returns_relevant_top_k() -> None:
    cards = [
        DeepCard(cap_id="01.a", what="LangGraph supervisor + planner"),
        DeepCard(cap_id="01.b", what="Constrained Router for plan"),
        DeepCard(cap_id="01.c", what="Unrelated content fully"),
        DeepCard(cap_id="01.d", what="LangGraph subgraph + Critic"),
        DeepCard(cap_id="01.e", what="planner + supervisor + LangGraph 编排"),
    ]
    pivot = cards[0]
    result = recommend_by_keyword(pivot, cards, k=3)
    ids = [r.cap_id for r in result]
    # 01.e 最相关(3 token 重合),01.d 次(1 token 重合)
    assert ids[0] == "01.e"
    assert "01.d" in ids
    assert "01.c" not in ids  # 无 token 重合,不入结果


def test_recommend_excludes_self() -> None:
    cards = [DeepCard(cap_id="a", what="LangGraph"), DeepCard(cap_id="b", what="LangGraph")]
    result = recommend_by_keyword(cards[0], cards, k=5)
    assert all(r.cap_id != "a" for r in result)


def test_recommend_empty_pivot() -> None:
    """pivot DeepCard 内容全空 — 返回 empty list"""
    pivot = DeepCard(cap_id="x")
    cards = [pivot, DeepCard(cap_id="y", what="something")]
    result = recommend_by_keyword(pivot, cards, k=3)
    assert result == []
