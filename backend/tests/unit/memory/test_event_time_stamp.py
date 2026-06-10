"""事件时间打戳:用对话发生日(episode created_at)当 valid_from。

对话流评估冒烟发现:抽取器把 valid_from 打成默认值(2025-01-01)而非对话日,
valid_from_is_event_time 断言据此红。修法:用 episode 事件时间覆盖。
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.memory.path_b_runner import stamp_event_time


def test_stamp_overrides_valid_from() -> None:
    edge = {"rel_type": "EXPRESSED_VIEW", "valid_from": datetime(2025, 1, 1, tzinfo=UTC)}
    event = datetime(2025, 3, 4, tzinfo=UTC)
    out = stamp_event_time(edge, event)
    assert out["valid_from"] == event
    assert out["rel_type"] == "EXPRESSED_VIEW"  # 其余字段不动


def test_stamp_does_not_mutate_input() -> None:
    edge = {"valid_from": datetime(2025, 1, 1, tzinfo=UTC)}
    event = datetime(2025, 3, 4, tzinfo=UTC)
    stamp_event_time(edge, event)
    assert edge["valid_from"] == datetime(2025, 1, 1, tzinfo=UTC)  # 原 dict 不变
