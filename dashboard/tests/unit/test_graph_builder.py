"""Plan 2 Task 2 — V3 graph_builder unit tests."""

from __future__ import annotations

from dashboard.derive.deep_card_types import CodeAnchor, DeepCard, SrsState
from dashboard.derive.graph_builder import build_graph_payload
from dashboard.derive.types import Capability


def test_graph_payload_basic_node_edge() -> None:
    caps = [
        Capability(
            id="01.a",
            dimension="prompt_context",
            name_cn="A",
            name_en="A",
            status="lit",
            derived_status="lit",
        ),
        Capability(
            id="02.b",
            dimension="tools_function",
            name_cn="B",
            name_en="B",
            status="lit",
            derived_status="lit",
        ),
    ]
    cards = [
        DeepCard(
            cap_id="01.a",
            linked_capabilities=["02.b"],
            srs_state=SrsState(confidence=3),
            code_anchors=[CodeAnchor(file="x.py", line=1)],
        ),
        DeepCard(cap_id="02.b", linked_capabilities=["01.a"], srs_state=SrsState(confidence=5)),
    ]
    payload = build_graph_payload(caps, cards)
    # 2 nodes
    assert len(payload["nodes"]) == 2
    a = next(n for n in payload["nodes"] if n["data"]["id"] == "01.a")
    assert a["data"]["dimension"] == "prompt_context"
    assert a["data"]["confidence"] == 3
    assert a["data"]["size"] == 2  # 1 code_anchor + 1
    # bi-directional link → 1 edge (dedupe)
    assert len(payload["edges"]) == 1
    edge = payload["edges"][0]
    assert {edge["data"]["source"], edge["data"]["target"]} == {"01.a", "02.b"}


def test_graph_self_loop_deduped() -> None:
    caps = [
        Capability(
            id="x.a",
            dimension="memory",
            name_cn="A",
            name_en="A",
            status="lit",
            derived_status="lit",
        )
    ]
    cards = [DeepCard(cap_id="x.a", linked_capabilities=["x.a"])]
    payload = build_graph_payload(caps, cards)
    assert payload["edges"] == []  # self-loop 去掉


def test_graph_no_deep_card_shows_dashed_node() -> None:
    """无 DeepCard 的 cap 仍出现在图,带 has_deep_card=False"""
    caps = [
        Capability(
            id="x.a",
            dimension="memory",
            name_cn="A",
            name_en="A",
            status="todo",
            derived_status="todo",
        )
    ]
    payload = build_graph_payload(caps, [])
    n = payload["nodes"][0]
    assert n["data"]["has_deep_card"] is False
    assert n["data"]["confidence"] == 0
    assert n["data"]["size"] == 1  # min size


def test_graph_filter_by_dimension() -> None:
    caps = [
        Capability(
            id="01.a",
            dimension="prompt_context",
            name_cn="A",
            name_en="A",
            status="lit",
            derived_status="lit",
        ),
        Capability(
            id="04.b",
            dimension="memory",
            name_cn="B",
            name_en="B",
            status="lit",
            derived_status="lit",
        ),
    ]
    payload = build_graph_payload(caps, [], filter_dimensions={"prompt_context"})
    assert len(payload["nodes"]) == 1
    assert payload["nodes"][0]["data"]["id"] == "01.a"


def test_graph_filter_low_confidence_only() -> None:
    caps = [
        Capability(
            id="x.a",
            dimension="memory",
            name_cn="A",
            name_en="A",
            status="lit",
            derived_status="lit",
        ),
        Capability(
            id="x.b",
            dimension="memory",
            name_cn="B",
            name_en="B",
            status="lit",
            derived_status="lit",
        ),
    ]
    cards = [
        DeepCard(cap_id="x.a", srs_state=SrsState(confidence=2)),
        DeepCard(cap_id="x.b", srs_state=SrsState(confidence=5)),
    ]
    payload = build_graph_payload(caps, cards, only_low_confidence=True)
    ids = {n["data"]["id"] for n in payload["nodes"]}
    assert "x.a" in ids and "x.b" not in ids
