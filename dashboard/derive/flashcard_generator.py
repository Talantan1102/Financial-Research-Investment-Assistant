"""DeepCard → Flashcard 机械模板派生(无 LLM)。spec § 5.5。"""

from __future__ import annotations

from datetime import UTC, datetime

from dashboard.derive.deep_card_types import DeepCard, Flashcard, SrsState


def generate_flashcards(card: DeepCard, *, cap_name_cn: str) -> list[Flashcard]:
    """生成 0-3 张闪卡。

    模板:
    - tradeoff:Q="Capability「{name}」的关键 tradeoff 是什么?" A=tradeoff 字段
    - alternatives:Q="Capability「{name}」在业界 alternatives 中我们选了哪个?为什么?"
      A=chosen + brief_tradeoff(仅 chosen_alternative 在 alternatives 名字中时)
    - lessons:Q="Capability「{name}」撞过什么坑?" A=lessons_learned(仅非空)
    """
    out: list[Flashcard] = []
    now = datetime.now(UTC)

    if card.tradeoff:
        out.append(
            Flashcard(
                id=f"{card.cap_id}::tradeoff",
                cap_id=card.cap_id,
                template_kind="tradeoff",
                question=f"Capability「{cap_name_cn}」的关键 tradeoff 是什么?",
                answer=card.tradeoff,
                srs_state=SrsState(),
                created_at=now,
            )
        )

    if card.chosen_alternative and card.alternatives:
        alt_match = next((a for a in card.alternatives if a.name == card.chosen_alternative), None)
        if alt_match is not None:
            out.append(
                Flashcard(
                    id=f"{card.cap_id}::alternatives",
                    cap_id=card.cap_id,
                    template_kind="alternatives",
                    question=(
                        f"Capability「{cap_name_cn}」在业界 alternatives 中我们选了哪个?为什么?"
                    ),
                    answer=f"{card.chosen_alternative} — {alt_match.brief_tradeoff}",
                    srs_state=SrsState(),
                    created_at=now,
                )
            )

    if card.lessons_learned:
        out.append(
            Flashcard(
                id=f"{card.cap_id}::lessons",
                cap_id=card.cap_id,
                template_kind="lessons",
                question=f"Capability「{cap_name_cn}」撞过什么坑?",
                answer=card.lessons_learned,
                srs_state=SrsState(),
                created_at=now,
            )
        )

    return out
