"""SM-2 SRS 算法 + Protocol 接口(为 FSRS v1.x 升级预留)。spec § 5.5。

参考 Wozniak (1990)。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol

from dashboard.derive.deep_card_types import SrsState


class SrsAlgo(Protocol):
    """SRS 算法接口 — Plan 3 SM-2,v1.x 可换 FSRS。"""

    def apply(self, state: SrsState, *, grade: int, now: datetime) -> SrsState:
        """输入当前 state + 自评 grade ∈ [0, 5],输出新 state。"""
        ...


class SM2Algo:
    """SM-2 算法 — Anki 经典。"""

    EF_MIN = 1.3

    def apply(self, state: SrsState, *, grade: int, now: datetime) -> SrsState:
        if not 0 <= grade <= 5:
            raise ValueError(f"grade must be 0..5, got {grade}")
        # ef 更新公式 (Wozniak)
        new_ef = state.ef + (0.1 - (5 - grade) * (0.08 + (5 - grade) * 0.02))
        new_ef = max(new_ef, self.EF_MIN)

        new_repetition: int
        new_interval: int
        if grade < 3:
            # 答错 — 重置
            new_repetition = 0
            new_interval = 1
        else:
            new_repetition = state.repetition + 1
            if new_repetition == 1:
                new_interval = 1
            elif new_repetition == 2:
                new_interval = 6
            else:
                new_interval = int(round(state.interval * state.ef))

        next_at = now + timedelta(days=new_interval)
        return SrsState(
            confidence=grade,
            ef=new_ef,
            interval=new_interval,
            repetition=new_repetition,
            last_reviewed_at=now,
            next_review_at=next_at,
        )


def schedule_next_review(state: SrsState, *, grade: int) -> SrsState:
    """Convenience wrapper — 用 SM-2 + now()。"""
    return SM2Algo().apply(state, grade=grade, now=datetime.now(UTC))
