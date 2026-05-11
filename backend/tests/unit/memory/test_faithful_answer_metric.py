"""L0 unit: faithful_answer metric — claim grounding check."""

from __future__ import annotations

from typing import Any

import pytest
from eval.memory.faithful_answer_metric import (
    claim_in_episode_text,
    faithful_answer,
)


class _MockJudge:
    def __init__(self) -> None:
        self._claims: list[str] = []
        self._verdicts: list[bool] = []
        self.ground_calls: int = 0

    def set_canned_decompose(self, claims: list[str]) -> None:
        self._claims = list(claims)

    def set_canned_verdicts(self, verdicts: list[bool]) -> None:
        self._verdicts = list(verdicts)

    async def decompose_to_claims(self, answer: str) -> list[str]:
        return list(self._claims)

    async def is_grounded(self, claim: str, facts: list[dict[str, Any]]) -> bool:
        v = self._verdicts[self.ground_calls]
        self.ground_calls += 1
        return v


@pytest.mark.asyncio
async def test_faithful_answer_all_grounded() -> None:
    judge = _MockJudge()
    judge.set_canned_decompose(["claim1", "claim2"])
    judge.set_canned_verdicts([True, True])
    facts = [
        {
            "edge_id": "e1",
            "source_episode_id": "ep1",
            "evidence_quote": "茅台 500 股",
            "_episode_text": "我重仓茅台 500 股, 看好白酒",
        }
    ]
    answer = "用户重仓茅台 500 股, 偏好白酒板块."
    p = await faithful_answer(answer=answer, retrieved_facts=facts, judge=judge)
    assert p == 1.0


@pytest.mark.asyncio
async def test_faithful_answer_hallucinated() -> None:
    judge = _MockJudge()
    judge.set_canned_decompose(["claim1", "claim_hallucination"])
    judge.set_canned_verdicts([True, False])
    facts = [{"edge_id": "e1", "source_episode_id": "ep1"}]
    answer = "用户重仓茅台. 用户讨厌科技股."
    p = await faithful_answer(answer=answer, retrieved_facts=facts, judge=judge)
    assert p == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_faithful_answer_empty() -> None:
    p = await faithful_answer(answer="", retrieved_facts=[], judge=None)
    assert p == 1.0


@pytest.mark.asyncio
async def test_faithful_answer_whitespace_only_answer_is_vacuous() -> None:
    p = await faithful_answer(answer="   \n  ", retrieved_facts=[], judge=None)
    assert p == 1.0


@pytest.mark.asyncio
async def test_faithful_answer_non_empty_requires_judge() -> None:
    with pytest.raises(ValueError, match="judge required"):
        await faithful_answer(answer="some answer", retrieved_facts=[], judge=None)


@pytest.mark.asyncio
async def test_faithful_answer_decompose_returns_empty_is_vacuous() -> None:
    """LLM 没识别出 atomic claim → 1.0 (不算 hallucination)."""
    judge = _MockJudge()
    judge.set_canned_decompose([])
    judge.set_canned_verdicts([])
    p = await faithful_answer(answer="some answer", retrieved_facts=[], judge=judge)
    assert p == 1.0


def test_claim_in_episode_text_substring_match() -> None:
    facts = [{"_episode_text": "我重仓茅台 500 股, 看好白酒"}]
    assert claim_in_episode_text("重仓茅台 500", facts) is True


def test_claim_in_episode_text_whitespace_tolerant() -> None:
    facts = [{"_episode_text": "我  重仓 茅台\n500 股"}]
    assert claim_in_episode_text("重仓茅台500股", facts) is True


def test_claim_in_episode_text_no_match() -> None:
    facts = [{"_episode_text": "我重仓茅台 500 股"}]
    assert claim_in_episode_text("用户讨厌科技股", facts) is False


def test_claim_in_episode_text_no_episode_text_field() -> None:
    facts = [{"edge_id": "e1"}]  # 缺 _episode_text
    assert claim_in_episode_text("茅台", facts) is False


def test_claim_in_episode_text_empty_claim() -> None:
    facts = [{"_episode_text": "anything"}]
    assert claim_in_episode_text("", facts) is False
    assert claim_in_episode_text("   ", facts) is False
