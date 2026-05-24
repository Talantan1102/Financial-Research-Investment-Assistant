"""DeepCard / SrsState / Provenance 类型验证。Plan 1 Task 1。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dashboard.derive.deep_card_types import (
    AlternativeItem,
    CodeAnchor,
    DeepCard,
    FieldProvenance,
    SrsState,
)


def test_deep_card_minimal_fields() -> None:
    """空 DeepCard 只需 cap_id;其他全部 optional。"""
    card = DeepCard(cap_id="01.constrained_schema")
    assert card.cap_id == "01.constrained_schema"
    assert card.what is None
    assert card.alternatives == []
    assert card.srs_state.confidence == 0
    assert card.prefill_source == "manual"


def test_deep_card_full_fields_roundtrip() -> None:
    card = DeepCard(
        cap_id="01.constrained_schema",
        what="LLM 输出强制走 JSON schema",
        why="避免自由生成导致下游解析失败",
        alternatives=[
            AlternativeItem(name="free-text + regex 后处理", brief_tradeoff="易碎"),
            AlternativeItem(name="constrained JSON schema", brief_tradeoff="model 端约束"),
        ],
        chosen_alternative="constrained JSON schema",
        tradeoff="选 schema 因为 OpenAI 兼容协议原生支持 response_format",
        code_anchors=[
            CodeAnchor(file="backend/app/services/llm_service.py", line=78, note="schema kwarg")
        ],
        linked_decisions=["abc123def456"],
        linked_specs=["docs/superpowers/specs/2026-05-05-v0.8.5-constrained-router-design.md"],
        linked_capabilities=["02.tool_registry"],
        provenance={
            "what": FieldProvenance(quote="LLM 输出强制走", source="docs/.../design.md#§2"),
        },
        srs_state=SrsState(confidence=3, ef=2.5, interval=4, repetition=2),
        prefill_source="hybrid",
    )
    dumped = card.model_dump_json()
    loaded = DeepCard.model_validate_json(dumped)
    assert loaded == card


def test_alternatives_items_have_required_fields() -> None:
    with pytest.raises(ValidationError):
        AlternativeItem(name="x")  # type: ignore[call-arg]  # missing brief_tradeoff


def test_chosen_alternative_must_match_one_of_alternatives() -> None:
    """chosen_alternative 必须是 alternatives 中某 name(放宽:Pydantic 不强制,运行时校验)。"""
    card = DeepCard(
        cap_id="x",
        alternatives=[AlternativeItem(name="A", brief_tradeoff="a")],
        chosen_alternative="B",  # 不匹配 — Plan 1 仅 Pydantic 不报,Plan 3 闪卡生成时再校验
    )
    assert card.chosen_alternative == "B"


def test_srs_state_defaults() -> None:
    s = SrsState()
    assert s.confidence == 0
    assert s.ef == 2.5
    assert s.interval == 0
    assert s.repetition == 0
    assert s.last_reviewed_at is None
    assert s.next_review_at is None
