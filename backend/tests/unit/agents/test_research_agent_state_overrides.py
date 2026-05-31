"""L0 — ResearchAgent state_overrides Pydantic validation.

C58: verifies that state_overrides applied via model_validate() enforce
ResearchState field constraints, rather than silently bypassing them via setattr.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.agents.research_agent import ResearchAgent

# ── helpers ───────────────────────────────────────────────────────────────────


def _make_agent(final_state: dict[str, Any] | None = None) -> ResearchAgent:
    """Build a ResearchAgent with a stubbed graph that returns final_state."""
    graph = MagicMock()
    graph.ainvoke = AsyncMock(return_value=final_state or {"report_markdown": "ok"})
    # astream_events is not used in run() path
    return ResearchAgent(graph=graph)


# ── C58: out-of-range override raises ValidationError ─────────────────────────


@pytest.mark.asyncio
async def test_run_rejects_out_of_range_planner_retry_count() -> None:
    """C58: state_overrides={'planner_retry_count': 99} must raise ValidationError
    (planner_retry_count has le=2 constraint) rather than silently storing 99."""
    from pydantic import ValidationError

    agent = _make_agent()
    with pytest.raises(ValidationError):
        await agent.run(
            user_input="test query",
            request_id="req-test-c58",
            state_overrides={"planner_retry_count": 99},
        )


@pytest.mark.asyncio
async def test_run_accepts_valid_override() -> None:
    """C58: a valid override is applied and the graph receives it."""
    agent = _make_agent()
    result = await agent.run(
        user_input="test query",
        request_id="req-test-c58-valid",
        state_overrides={"planner_retry_count": 1},
    )
    # graph.ainvoke was called with a dict containing planner_retry_count=1
    call_args = agent._graph.ainvoke.call_args
    initial_dict: dict[str, Any] = call_args[0][0]
    assert initial_dict["planner_retry_count"] == 1
    assert result.request_id == "req-test-c58-valid"


@pytest.mark.asyncio
async def test_run_streaming_rejects_out_of_range_planner_retry_count() -> None:
    """C58: run_streaming also raises ValidationError on invalid override."""
    from pydantic import ValidationError

    graph = MagicMock()
    # astream_events is an async generator — use AsyncMock with an empty iterator
    graph.astream_events = MagicMock(return_value=aiter([]))
    agent = ResearchAgent(graph=graph)

    with pytest.raises(ValidationError):
        # Collect the async generator; the ValidationError raises before astream_events
        async for _ in agent.run_streaming(
            user_input="test",
            request_id="req-stream-c58",
            state_overrides={"planner_retry_count": 99},
        ):
            pass


@pytest.mark.asyncio
async def test_run_ignores_unknown_override_keys() -> None:
    """C58: keys not present on ResearchState are silently dropped (no crash)."""
    agent = _make_agent()
    # Should not raise even though 'nonexistent_field' is unknown
    result = await agent.run(
        user_input="query",
        request_id="req-unknown-key",
        state_overrides={"nonexistent_field": "ignored"},
    )
    assert result.request_id == "req-unknown-key"


# ── helpers for async iteration ───────────────────────────────────────────────


async def aiter(items):
    for item in items:
        yield item
