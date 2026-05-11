"""L0 unit tests for ConflictResolver judge — 4-action + fail-safe."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from app.memory.conflict_resolver import (
    ConflictAction,
    ConflictResolver,
    ConflictVerdict,
)


@pytest.mark.asyncio
async def test_judge_returns_update_validity_for_evolution() -> None:
    """新事实是现实演化(买了→卖了) → update_validity."""
    fake_llm = AsyncMock()
    fake_llm.chat.return_value = json.dumps(
        {
            "action": "update_validity",
            "reasoning": "用户从持有变为已卖",
        }
    )

    resolver = ConflictResolver(llm_client=fake_llm)
    verdict = await resolver.judge(
        new_edge_summary="SOLD User → 600519.SH at 2026-04",
        existing_edges_summary=["HOLDS User → 600519.SH (valid_from=2024-08, ongoing)"],
    )
    assert verdict.action == ConflictAction.UPDATE_VALIDITY
    assert "卖" in verdict.reasoning


@pytest.mark.asyncio
async def test_judge_returns_contradict_for_correction() -> None:
    """系统记错纠正 → contradict_existing."""
    fake_llm = AsyncMock()
    fake_llm.chat.return_value = json.dumps(
        {
            "action": "contradict_existing",
            "reasoning": "用户澄清记录有误, 实际买的是五粮液",
        }
    )

    resolver = ConflictResolver(llm_client=fake_llm)
    verdict = await resolver.judge(
        new_edge_summary="HOLDS User → 000858.SZ",
        existing_edges_summary=["HOLDS User → 600519.SH (recorded 2026-03)"],
    )
    assert verdict.action == ConflictAction.CONTRADICT_EXISTING


@pytest.mark.asyncio
async def test_judge_returns_no_op_for_duplicate() -> None:
    """完全重复 → no_op."""
    fake_llm = AsyncMock()
    fake_llm.chat.return_value = json.dumps({"action": "no_op", "reasoning": "重复"})

    resolver = ConflictResolver(llm_client=fake_llm)
    verdict = await resolver.judge(
        new_edge_summary="HOLDS User → 600519.SH",
        existing_edges_summary=["HOLDS User → 600519.SH (valid_from same)"],
    )
    assert verdict.action == ConflictAction.NO_OP


@pytest.mark.asyncio
async def test_judge_failsafe_to_append_new_on_invalid_json() -> None:
    """LLM 返回非 JSON → fail-safe 默认 append_new (保守, 不丢信息)."""
    fake_llm = AsyncMock()
    fake_llm.chat.return_value = "ah I'm not sure"

    resolver = ConflictResolver(llm_client=fake_llm)
    verdict = await resolver.judge(new_edge_summary="x", existing_edges_summary=["y"])
    assert verdict.action == ConflictAction.APPEND_NEW
    assert "fail-safe" in verdict.reasoning.lower()


@pytest.mark.asyncio
async def test_judge_failsafe_on_exception() -> None:
    """LLM call 抛异常 → fail-safe append_new."""
    fake_llm = AsyncMock()
    fake_llm.chat.side_effect = RuntimeError("LLM api timeout")

    resolver = ConflictResolver(llm_client=fake_llm)
    verdict = await resolver.judge(new_edge_summary="x", existing_edges_summary=["y"])
    assert verdict.action == ConflictAction.APPEND_NEW


@pytest.mark.asyncio
async def test_judge_unknown_action_failsafe() -> None:
    """LLM 返回 valid JSON 但 action 不在 4 类 → fail-safe append_new."""
    fake_llm = AsyncMock()
    fake_llm.chat.return_value = json.dumps(
        {
            "action": "delete_everything",
            "reasoning": "I want to delete",
        }
    )

    resolver = ConflictResolver(llm_client=fake_llm)
    verdict = await resolver.judge(new_edge_summary="x", existing_edges_summary=["y"])
    assert verdict.action == ConflictAction.APPEND_NEW


def test_conflict_verdict_is_pydantic() -> None:
    """ConflictVerdict 可序列化, 4 action 完整."""
    v = ConflictVerdict(action=ConflictAction.NO_OP, reasoning="x")
    assert v.action.value == "no_op"
    assert {a.value for a in ConflictAction} == {
        "update_validity",
        "contradict_existing",
        "append_new",
        "no_op",
    }
