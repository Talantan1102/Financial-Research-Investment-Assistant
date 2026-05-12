"""SM-2 SRS 算法单元测试。Plan 3 Task 1。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from dashboard.derive.deep_card_types import SrsState
from dashboard.derive.srs import SM2Algo, schedule_next_review


def test_first_review_grade_5_advances_to_interval_1() -> None:
    """新卡(repetition=0)第一次得 5 → repetition=1, interval=1, ef 微升。"""
    s = SrsState()
    new = SM2Algo().apply(s, grade=5, now=datetime(2026, 5, 12, tzinfo=UTC))
    assert new.repetition == 1
    assert new.interval == 1
    assert new.ef > 2.5  # 高分 ef 上升
    assert new.next_review_at == datetime(2026, 5, 13, tzinfo=UTC)


def test_second_review_grade_4_advances_to_interval_6() -> None:
    """repetition=1, interval=1 → 得 4 → repetition=2, interval=6。"""
    s = SrsState(
        repetition=1, interval=1, ef=2.5, last_reviewed_at=datetime(2026, 5, 11, tzinfo=UTC)
    )
    new = SM2Algo().apply(s, grade=4, now=datetime(2026, 5, 12, tzinfo=UTC))
    assert new.repetition == 2
    assert new.interval == 6
    assert new.next_review_at == datetime(2026, 5, 18, tzinfo=UTC)


def test_third_review_uses_ef_multiplication() -> None:
    """repetition>=2 时 interval = prev_interval * ef。"""
    s = SrsState(
        repetition=2, interval=6, ef=2.5, last_reviewed_at=datetime(2026, 5, 1, tzinfo=UTC)
    )
    new = SM2Algo().apply(s, grade=4, now=datetime(2026, 5, 7, tzinfo=UTC))
    assert new.repetition == 3
    assert new.interval == 15  # 6 * 2.5 = 15
    expected = datetime(2026, 5, 7, tzinfo=UTC) + timedelta(days=15)
    assert new.next_review_at == expected


def test_low_grade_resets_repetition() -> None:
    """grade < 3 → repetition=0, interval=1, ef 下降。"""
    s = SrsState(
        repetition=5, interval=30, ef=2.8, last_reviewed_at=datetime(2026, 5, 1, tzinfo=UTC)
    )
    new = SM2Algo().apply(s, grade=1, now=datetime(2026, 5, 31, tzinfo=UTC))
    assert new.repetition == 0
    assert new.interval == 1
    assert new.ef < 2.8


def test_ef_lower_bound() -> None:
    """ef 不能低于 1.3。"""
    s = SrsState(ef=1.3)
    new = SM2Algo().apply(s, grade=0, now=datetime(2026, 5, 12, tzinfo=UTC))
    assert new.ef == 1.3


def test_confidence_field_set_from_grade() -> None:
    """confidence 反映上次自评(用于 V3 节点边框 / V1 chip)。"""
    s = SrsState()
    new = SM2Algo().apply(s, grade=4, now=datetime(2026, 5, 12, tzinfo=UTC))
    assert new.confidence == 4


def test_schedule_next_review_convenience() -> None:
    """top-level helper:输入 state + grade,返回 new state。"""
    s = SrsState()
    new = schedule_next_review(s, grade=5)
    assert new.repetition == 1
