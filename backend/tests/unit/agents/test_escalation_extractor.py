"""L0 — EscalationExtractor (E9 LLM extraction quality)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from app.agents.escalation_extractor import EscalationExtractor
from app.agents.escalation_protocol import EscalationPacket
from app.services.llm_response import LLMResponse
from app.services.llm_service import LLMService


def _llm(content: str) -> LLMService:
    m = MagicMock(spec=LLMService)
    m.chat.return_value = LLMResponse(
        content=content,
        tier="fast",
        prompt_tokens=10,
        completion_tokens=20,
        total_tokens=30,
        cost_cny=0.001,
        latency_ms=100,
        model="qwen-plus",
    )
    return m


_FULL_RESP = json.dumps(
    {
        "explicit_task": {
            "raw_last_user_turn": "深度尽调 ICBC",
            "extracted_intent": "full_due_diligence",
            "target_ts_code": "601398.SH",
            "target_entity_name": "工商银行",
            "user_extra_message": None,
        },
        "chat_derived_signals": {
            "entities": [
                {
                    "name": "工商银行",
                    "ts_code": "601398.SH",
                    "role": "primary_target",
                    "mention_turn_indices": [0, 2],
                },
            ],
            "preferences": [
                {"text": "风控优先", "category": "risk_tolerance", "confidence": 0.85},
            ],
            "open_questions": ["招行的不良率怎么样"],
            "inferred_persona": "保守型零售投资者",
            "extraction_confidence": 0.78,
        },
        "known_facts": {
            "tool_results": [
                {
                    "tool_name": "get_stock_quote",
                    "tool_args": {"ts_code": "601398.SH"},
                    "result_summary": "现价 6.45 元",
                    "cached_at": "2026-05-09T12:00:00+00:00",
                    "cache_id": "anon::get_stock_quote::abc",
                },
            ],
        },
        "session_metadata": {
            "chat_session_id": "chat-abc",
            "chat_turn_count": 5,
            "chat_history_summary": "用户问 ICBC 现价 + 不良率",
            "user_confirmed_at": "2026-05-09T12:01:00+00:00",
            "user_edits": [],
        },
        "missing_field_hints": [],
    }
)


@pytest.mark.asyncio
async def test_extractor_full_fill_passthrough():
    llm = _llm(_FULL_RESP)
    ext = EscalationExtractor(llm=llm)
    pkt = await ext.run(
        chat_session_id="chat-abc",
        chat_turn_count=5,
        chat_history_summary="用户问 ICBC 现价 + 不良率",
        history=[
            {"role": "user", "content": "ICBC 现价"},
            {"role": "assistant", "content": "..."},
            {"role": "user", "content": "ICBC 不良率"},
            {"role": "assistant", "content": "..."},
            {"role": "user", "content": "深度尽调 ICBC"},
        ],
        cached_tool_results=[
            {
                "tool_name": "get_stock_quote",
                "tool_args": {"ts_code": "601398.SH"},
                "result_summary": "现价 6.45 元",
                "cache_id": "anon::get_stock_quote::abc",
                "cached_at": "2026-05-09T12:00:00Z",
            },
        ],
    )
    assert isinstance(pkt, EscalationPacket)
    assert pkt.explicit_task.target_ts_code == "601398.SH"
    assert pkt.chat_derived_signals.preferences[0].confidence == 0.85
    assert pkt.known_facts.tool_results[0].cache_id == "anon::get_stock_quote::abc"


@pytest.mark.asyncio
async def test_extractor_emits_missing_field_hints():
    resp = json.dumps(
        {
            "explicit_task": {
                "raw_last_user_turn": "看一下 X 的尽调",
                "extracted_intent": "full_due_diligence",
                "target_ts_code": None,
                "target_entity_name": None,
                "user_extra_message": None,
            },
            "chat_derived_signals": {
                "entities": [],
                "preferences": [],
                "open_questions": [],
                "inferred_persona": None,
                "extraction_confidence": 0.2,
            },
            "known_facts": {"tool_results": []},
            "session_metadata": {
                "chat_session_id": "chat-abc",
                "chat_turn_count": 1,
                "chat_history_summary": None,
                "user_confirmed_at": "2026-05-09T12:00:00+00:00",
                "user_edits": [],
            },
            "missing_field_hints": [
                {
                    "field_path": "explicit_task.target_ts_code",
                    "reason": "llm_uncertain",
                    "llm_question_for_user": "您说的 'X' 是哪只股票?",
                },
            ],
        }
    )
    llm = _llm(resp)
    ext = EscalationExtractor(llm=llm)
    pkt = await ext.run(
        chat_session_id="chat-abc",
        chat_turn_count=1,
        chat_history_summary=None,
        history=[{"role": "user", "content": "看一下 X 的尽调"}],
        cached_tool_results=[],
    )
    assert pkt.missing_field_hints[0].reason == "llm_uncertain"
    assert "X" in pkt.missing_field_hints[0].llm_question_for_user


@pytest.mark.asyncio
async def test_extractor_filters_hallucinated_tool_results():
    resp = json.dumps(
        {
            "explicit_task": {
                "raw_last_user_turn": "x",
                "extracted_intent": "x",
                "target_ts_code": None,
                "target_entity_name": None,
                "user_extra_message": None,
            },
            "chat_derived_signals": {
                "entities": [],
                "preferences": [],
                "open_questions": [],
                "inferred_persona": None,
                "extraction_confidence": 0.5,
            },
            "known_facts": {
                "tool_results": [
                    {
                        "tool_name": "get_stock_quote",
                        "tool_args": {},
                        "result_summary": "...",
                        "cached_at": "2026-05-09T12:00:00+00:00",
                        "cache_id": "fake_id_not_in_cache",
                    },
                ],
            },
            "session_metadata": {
                "chat_session_id": "s",
                "chat_turn_count": 1,
                "chat_history_summary": None,
                "user_confirmed_at": "2026-05-09T12:00:00+00:00",
                "user_edits": [],
            },
            "missing_field_hints": [],
        }
    )
    llm = _llm(resp)
    ext = EscalationExtractor(llm=llm)
    pkt = await ext.run(
        chat_session_id="s",
        chat_turn_count=1,
        chat_history_summary=None,
        history=[{"role": "user", "content": "x"}],
        cached_tool_results=[],
    )
    assert pkt.known_facts.tool_results == []


@pytest.mark.asyncio
async def test_extractor_json_parse_failure_returns_minimal_packet():
    llm = _llm("oops, this is not JSON")
    ext = EscalationExtractor(llm=llm)
    pkt = await ext.run(
        chat_session_id="s",
        chat_turn_count=1,
        chat_history_summary=None,
        history=[{"role": "user", "content": "do research"}],
        cached_tool_results=[],
    )
    assert pkt.chat_derived_signals.extraction_confidence == 0.0
    assert any(h.field_path == "explicit_task.extracted_intent" for h in pkt.missing_field_hints)


@pytest.mark.asyncio
async def test_extractor_passes_full_history_to_llm():
    llm = _llm(_FULL_RESP)
    ext = EscalationExtractor(llm=llm)
    history = [
        {"role": "user", "content": "ICBC 现价"},
        {"role": "assistant", "content": "6.45 元"},
        {"role": "user", "content": "对比招行 (600036)"},
        {"role": "assistant", "content": "..."},
        {"role": "user", "content": "深度尽调 ICBC"},
    ]
    await ext.run(
        chat_session_id="s",
        chat_turn_count=5,
        chat_history_summary=None,
        history=history,
        cached_tool_results=[],
    )
    prompt_arg = llm.chat.call_args.kwargs.get("prompt") or llm.chat.call_args.args[0]
    for turn in history:
        assert turn["content"][:30] in prompt_arg


def test_extractor_prompt_requests_5_new_v1x_fields() -> None:
    """v1.x: prompt instructs LLM to fill 5 new fields."""
    from app.agents.escalation_extractor import _EXTRACTOR_PROMPT_TEMPLATE

    for field in (
        "escalation_intent",
        "discussion_focus",
        "explicit_exclusions",
        "llm_self_confidence",
        "confidence_rationale",
    ):
        assert field in _EXTRACTOR_PROMPT_TEMPLATE, f"prompt missing field: {field}"


def test_extractor_prompt_specifies_field_constraints() -> None:
    """Prompt should specify length caps + list size caps so LLM doesn't overshoot."""
    from app.agents.escalation_extractor import _EXTRACTOR_PROMPT_TEMPLATE

    # Length / count hints
    assert "200" in _EXTRACTOR_PROMPT_TEMPLATE  # intent max length
    assert "30" in _EXTRACTOR_PROMPT_TEMPLATE  # per-item length
    assert (
        "high" in _EXTRACTOR_PROMPT_TEMPLATE.lower()
        and "medium" in _EXTRACTOR_PROMPT_TEMPLATE.lower()
        and "low" in _EXTRACTOR_PROMPT_TEMPLATE.lower()
    )


def test_extractor_prompt_has_extraction_rule_for_v1x_fields() -> None:
    """Prompt should give the LLM guidance on how to extract each new field."""
    from app.agents.escalation_extractor import _EXTRACTOR_PROMPT_TEMPLATE

    # Heuristic — extraction rules section mentions distillation, focus, exclusion semantics
    text_lower = _EXTRACTOR_PROMPT_TEMPLATE.lower()
    # Either explicit Chinese instruction or English keyword
    assert (
        "蒸馏" in _EXTRACTOR_PROMPT_TEMPLATE
        or "distill" in text_lower
        or "提炼" in _EXTRACTOR_PROMPT_TEMPLATE
    )
    assert "关注点" in _EXTRACTOR_PROMPT_TEMPLATE or "focus" in text_lower
    assert (
        "不关注" in _EXTRACTOR_PROMPT_TEMPLATE
        or "排除" in _EXTRACTOR_PROMPT_TEMPLATE
        or "exclu" in text_lower
    )
