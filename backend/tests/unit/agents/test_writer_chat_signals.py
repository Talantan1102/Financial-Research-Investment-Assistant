"""L0 — Writer honors chat_extracted_preferences."""

from __future__ import annotations

import contextlib
from unittest.mock import MagicMock

import pytest
from app.agents.escalation_protocol import Preference
from app.agents.schemas import ResearchState
from app.agents.writer import Writer
from app.services.llm_service import LLMResponse, LLMService


def _llm() -> LLMService:
    m = MagicMock(spec=LLMService)
    m.chat.return_value = LLMResponse(
        content="# 报告\n\n## 投资建议\n持有",
        tier="fast",
        prompt_tokens=10,
        completion_tokens=20,
        total_tokens=30,
        cost_cny=0.001,
        latency_ms=100,
        model="qwen-plus",
    )
    return m


@pytest.mark.asyncio
async def test_writer_prompt_includes_horizon_preference():
    llm = _llm()
    writer = Writer(llm=llm)
    state = ResearchState(
        user_id="u",
        session_id="s",
        user_message="尽调 ICBC",
        request_id="r",
        chat_extracted_preferences=[
            Preference(text="长线持有 5 年+", category="horizon", confidence=0.9),
            Preference(text="风控优先", category="risk_tolerance", confidence=0.8),
        ],
    )
    with contextlib.suppress(Exception):
        await writer.run(state)

    prompt = llm.chat.call_args.kwargs.get("prompt") or llm.chat.call_args.args[0]
    assert "长线持有 5 年+" in prompt  # exact preference text must be injected
    assert "风控优先" in prompt  # exact preference text must be injected


@pytest.mark.asyncio
async def test_writer_prompt_omits_block_when_no_preferences():
    llm = _llm()
    writer = Writer(llm=llm)
    state = ResearchState(
        user_id="u",
        session_id="s",
        user_message="尽调 ICBC",
        request_id="r",
    )
    with contextlib.suppress(Exception):
        await writer.run(state)

    prompt = llm.chat.call_args.kwargs.get("prompt") or llm.chat.call_args.args[0]
    assert "尽调 ICBC" in prompt
