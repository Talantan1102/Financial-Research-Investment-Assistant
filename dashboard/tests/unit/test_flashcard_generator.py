"""闪卡模板派生单元测试。Plan 3 Task 2。"""

from __future__ import annotations

from dashboard.derive.deep_card_types import AlternativeItem, DeepCard
from dashboard.derive.flashcard_generator import generate_flashcards


def test_generates_tradeoff_card() -> None:
    card = DeepCard(cap_id="x.a", tradeoff="选 schema 因为协议支持")
    cards = generate_flashcards(card, cap_name_cn="X.A")
    kinds = {c.template_kind for c in cards}
    assert "tradeoff" in kinds
    tc = next(c for c in cards if c.template_kind == "tradeoff")
    assert "X.A" in tc.question
    assert tc.answer == "选 schema 因为协议支持"


def test_generates_alternatives_card_with_chosen() -> None:
    card = DeepCard(
        cap_id="x",
        chosen_alternative="constrained JSON schema",
        alternatives=[
            AlternativeItem(name="free-text + regex", brief_tradeoff="易碎"),
            AlternativeItem(name="constrained JSON schema", brief_tradeoff="model 端约束"),
        ],
    )
    cards = generate_flashcards(card, cap_name_cn="X")
    ac = next(c for c in cards if c.template_kind == "alternatives")
    assert "constrained JSON schema" in ac.answer
    assert "model 端约束" in ac.answer


def test_skip_alternatives_card_if_no_chosen() -> None:
    """chosen_alternative 缺 → 不生成 alternatives 闪卡。"""
    card = DeepCard(cap_id="x", alternatives=[AlternativeItem(name="A", brief_tradeoff="a")])
    cards = generate_flashcards(card, cap_name_cn="X")
    assert all(c.template_kind != "alternatives" for c in cards)


def test_generates_lessons_card_if_non_empty() -> None:
    card = DeepCard(cap_id="x", lessons_learned="撞过 ruff 行宽")
    cards = generate_flashcards(card, cap_name_cn="X")
    lc = next(c for c in cards if c.template_kind == "lessons")
    assert lc.answer == "撞过 ruff 行宽"


def test_skip_lessons_card_if_empty() -> None:
    card = DeepCard(cap_id="x", tradeoff="t")  # no lessons_learned
    cards = generate_flashcards(card, cap_name_cn="X")
    assert all(c.template_kind != "lessons" for c in cards)


def test_no_content_no_cards() -> None:
    """DeepCard 全空 → 不生成。"""
    card = DeepCard(cap_id="x")
    cards = generate_flashcards(card, cap_name_cn="X")
    assert cards == []


def test_flashcard_id_format() -> None:
    card = DeepCard(cap_id="x", tradeoff="t")
    cards = generate_flashcards(card, cap_name_cn="X")
    assert any(c.id == "x::tradeoff" for c in cards)


def test_chosen_not_in_alternatives_skipped() -> None:
    """chosen_alternative 不在 alternatives 名字中 → 不生成 alternatives 闪卡
    (spec § 4.1 提到的运行时校验)。"""
    card = DeepCard(
        cap_id="x",
        chosen_alternative="bogus",
        alternatives=[AlternativeItem(name="A", brief_tradeoff="a")],
    )
    cards = generate_flashcards(card, cap_name_cn="X")
    assert all(c.template_kind != "alternatives" for c in cards)
