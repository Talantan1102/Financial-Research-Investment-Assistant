"""Plan 2 Task 7 — V4 story_builder unit tests."""

from __future__ import annotations

from datetime import UTC, datetime

from dashboard.derive.deep_card_types import DeepCard
from dashboard.derive.story_builder import build_story_cards
from dashboard.derive.types import Capability


def test_story_card_has_three_sections() -> None:
    cap = Capability(
        id="x.a",
        dimension="context",
        name_cn="A",
        name_en="A",
        status="lit",
        derived_status="lit",
    )
    card = DeepCard(
        cap_id="x.a",
        why="为了避免下游解析失败",
        tradeoff="选 schema 因为 OpenAI 协议支持",
        lessons_learned="撞过 LLM 输出 escape 错误",
    )
    cards = build_story_cards([cap], [card], commit_times={"x.a": "2026-05-01T00:00:00+00:00"})
    assert len(cards) == 1
    sc = cards[0]
    assert sc.cap_id == "x.a"
    assert "为了避免" in sc.problem
    assert "选 schema" in sc.decision
    assert "escape 错误" in sc.outcome


def test_story_sort_by_time() -> None:
    caps = [
        Capability(
            id="x.a",
            dimension="context",
            name_cn="A",
            name_en="A",
            status="lit",
            derived_status="lit",
        ),
        Capability(
            id="x.b",
            dimension="context",
            name_cn="B",
            name_en="B",
            status="lit",
            derived_status="lit",
        ),
    ]
    cards = [
        DeepCard(cap_id="x.a", why="...", tradeoff="..."),
        DeepCard(cap_id="x.b", why="...", tradeoff="..."),
    ]
    times = {"x.a": "2026-05-10T00:00:00+00:00", "x.b": "2026-04-01T00:00:00+00:00"}
    out = build_story_cards(caps, cards, commit_times=times)
    assert out[0].cap_id == "x.b"  # earlier first
    assert out[1].cap_id == "x.a"


def test_story_fallback_to_prefill_at() -> None:
    """commit_times 缺 → 用 DeepCard.prefill_at;两者都无 → 'no_time_group'"""
    caps = [
        Capability(
            id="x.a",
            dimension="context",
            name_cn="A",
            name_en="A",
            status="lit",
            derived_status="lit",
        ),
    ]
    cards = [
        DeepCard(
            cap_id="x.a",
            why="w",
            tradeoff="t",
            prefill_at=datetime(2026, 3, 1, tzinfo=UTC),
        )
    ]
    out = build_story_cards(caps, cards, commit_times={})
    assert out[0].sort_time is not None
    assert "2026-03-01" in out[0].sort_time


def test_story_no_time_group_sentinel() -> None:
    caps = [
        Capability(
            id="x.a",
            dimension="context",
            name_cn="A",
            name_en="A",
            status="lit",
            derived_status="lit",
        )
    ]
    cards = [DeepCard(cap_id="x.a", why="w", tradeoff="t")]
    out = build_story_cards(caps, cards, commit_times={})
    assert out[0].in_no_time_group is True
    assert out[0].sort_time is None


def test_story_filter_by_dimension() -> None:
    caps = [
        Capability(
            id="01.a",
            dimension="context",
            name_cn="A",
            name_en="A",
            status="lit",
            derived_status="lit",
        ),
        Capability(
            id="04.b",
            dimension="lifecycle",
            name_cn="B",
            name_en="B",
            status="lit",
            derived_status="lit",
        ),
    ]
    cards = [
        DeepCard(cap_id="01.a", why="...", tradeoff="..."),
        DeepCard(cap_id="04.b", why="...", tradeoff="..."),
    ]
    out = build_story_cards(caps, cards, commit_times={}, filter_dimensions={"context"})
    assert len(out) == 1
    assert out[0].cap_id == "01.a"


def test_story_filter_time_window() -> None:
    caps = [
        Capability(
            id="x.a",
            dimension="context",
            name_cn="A",
            name_en="A",
            status="lit",
            derived_status="lit",
        ),
        Capability(
            id="x.b",
            dimension="context",
            name_cn="B",
            name_en="B",
            status="lit",
            derived_status="lit",
        ),
    ]
    cards = [
        DeepCard(cap_id="x.a", why="...", tradeoff="..."),
        DeepCard(cap_id="x.b", why="...", tradeoff="..."),
    ]
    times = {"x.a": "2026-05-10T00:00:00+00:00", "x.b": "2026-04-01T00:00:00+00:00"}
    out = build_story_cards(caps, cards, commit_times=times, time_after="2026-05-01")
    assert len(out) == 1
    assert out[0].cap_id == "x.a"
