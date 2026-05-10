"""L0 — BatchExtractor.extract_batch(spec § 4 优化 #2)."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from app.memory.batch_extractor import BatchExtractedFact, BatchExtractor
from app.memory.models import ChatMemoryEpisode


def _make_episode(idx: int, text: str) -> ChatMemoryEpisode:
    return ChatMemoryEpisode(
        episode_id=uuid4(),
        user_id=uuid4(),
        session_id=uuid4(),
        episode_index=idx,
        user_message_text=text,
        agent_response_text="ok",
        source_kind="chat_turn",
    )


class FakeLLM:
    """记录调用次数 + canned response."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    async def chat_async(self, *, system_prompt: str, user_prompt: str, model: str) -> str:
        self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt})
        return self.response


def _build_canned(eids: list[UUID]) -> str:
    parts = [
        '{"source_episode_id":"'
        + str(eid)
        + '","source_label":"User","target_label":"贵州茅台",'
        + '"rel_type":"HOLDS","reasoning":"加仓","importance":0.9,'
        + '"evidence_quote":"加仓 600519.SH","valid_from":"2026-05-11T00:00:00+00:00"}'
        for eid in eids
    ]
    return '{"facts":[' + ",".join(parts) + "]}"


@pytest.mark.asyncio
async def test_batch_5_episodes_single_llm_call() -> None:
    eps = [_make_episode(i, f"我加仓 600519.SH 在 episode {i}") for i in range(5)]
    llm = FakeLLM(_build_canned([ep.episode_id for ep in eps]))
    extractor = BatchExtractor(llm=llm, model="qwen-plus")
    facts = await extractor.extract_batch(eps)

    assert len(facts) == 5
    assert len(llm.calls) == 1, "5 episodes → 1 LLM call(优化 #2 摊薄 system prompt)"
    eid_set = {ep.episode_id for ep in eps}
    for f in facts:
        assert f.source_episode_id in eid_set


@pytest.mark.asyncio
async def test_single_episode_degenerates_to_one_call() -> None:
    eps = [_make_episode(0, "我加仓茅台 600519.SH 500 股")]
    llm = FakeLLM(_build_canned([eps[0].episode_id]))
    extractor = BatchExtractor(llm=llm, model="qwen-plus")
    facts = await extractor.extract_batch(eps)
    assert len(facts) == 1
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_empty_input_no_call() -> None:
    llm = FakeLLM("")
    extractor = BatchExtractor(llm=llm, model="qwen-plus")
    facts = await extractor.extract_batch([])
    assert facts == []
    assert len(llm.calls) == 0


@pytest.mark.asyncio
async def test_prompt_contains_episode_id_anchors() -> None:
    """prompt 必须以 <episode id="..."> 包裹每个 episode 让 LLM 标归属."""
    eps = [_make_episode(0, "买茅台 600519.SH"), _make_episode(1, "卖五粮液 000858.SZ")]
    llm = FakeLLM('{"facts":[]}')
    extractor = BatchExtractor(llm=llm, model="qwen-plus")
    await extractor.extract_batch(eps)
    user_prompt = llm.calls[0]["user_prompt"]
    for ep in eps:
        assert f'id="{ep.episode_id}"' in user_prompt


@pytest.mark.asyncio
async def test_invalid_json_returns_empty() -> None:
    """LLM 返回 invalid JSON → 返回 [] 不抛(spec § 4 失败矩阵)."""
    eps = [_make_episode(0, "x" * 60)]
    llm = FakeLLM("not json at all")
    extractor = BatchExtractor(llm=llm, model="qwen-plus")
    facts = await extractor.extract_batch(eps)
    assert facts == []


@pytest.mark.asyncio
async def test_hallucinated_episode_id_dropped() -> None:
    """LLM 输出不在输入集合的 episode_id → 丢弃."""
    eps = [_make_episode(0, "x" * 60)]
    fake_eid = uuid4()
    canned = _build_canned([fake_eid])
    llm = FakeLLM(canned)
    extractor = BatchExtractor(llm=llm, model="qwen-plus")
    facts = await extractor.extract_batch(eps)
    assert facts == [], "fake episode_id 必须丢弃, 不污染下游"


@pytest.mark.asyncio
async def test_extracted_fact_has_required_fields() -> None:
    eps = [_make_episode(0, "我加仓 600519.SH 500 股")]
    llm = FakeLLM(_build_canned([eps[0].episode_id]))
    extractor = BatchExtractor(llm=llm, model="qwen-plus")
    facts = await extractor.extract_batch(eps)
    f = facts[0]
    assert isinstance(f, BatchExtractedFact)
    assert f.source_label == "User"
    assert f.target_label == "贵州茅台"
    assert f.rel_type == "HOLDS"
    assert f.importance == 0.9
    assert f.evidence_quote != ""
