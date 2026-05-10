"""L0 — Agent ABC contract + DispatchSubAgent interface placeholder."""

from pathlib import Path

import pytest
from app.agents.base import Agent
from app.agents.schemas import GraphState, StepResult
from app.services.llm_mock_client import MockLLMClient
from app.services.llm_response import Tier
from app.services.llm_service import LLMService


def _make_state() -> GraphState:
    return GraphState(
        user_id="u",
        session_id="s",
        user_message="hi",
        request_id="req-test1234",
        trace_request_id="req-test1234",
    )


def test_agent_subclass_must_implement_step(
    monkeypatch: pytest.MonkeyPatch,
    mock_llm_client: MockLLMClient,
) -> None:
    monkeypatch.setenv("LLM_MODE", "mock")

    class _Incomplete(Agent):
        name = "incomplete"
        model_tier: Tier = "fast"

    svc = LLMService(client=mock_llm_client)
    with pytest.raises(TypeError):
        _Incomplete(llm=svc)  # type: ignore[abstract]


def test_minimal_subclass_works(
    monkeypatch: pytest.MonkeyPatch,
    mock_llm_client: MockLLMClient,
) -> None:
    monkeypatch.setenv("LLM_MODE", "mock")

    class _Minimal(Agent):
        name = "minimal"
        model_tier: Tier = "fast"

        def step(self, state: GraphState) -> StepResult:
            return StepResult(state_update={"final_response": "ok"}, span_metadata={})

    svc = LLMService(client=mock_llm_client)
    a = _Minimal(llm=svc)
    sr = a.step(_make_state())
    assert sr.state_update["final_response"] == "ok"


def test_dispatch_subagent_placeholder_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """v0: DispatchSubAgent 接口在 base 占位但默认 raise NotImplementedError —
    v0.5 启用 Critic 时再 override。"""
    monkeypatch.setenv("LLM_MODE", "mock")

    class _A(Agent):
        name = "a"
        model_tier: Tier = "fast"

        def step(self, state: GraphState) -> StepResult:
            return StepResult(state_update={})

    from app.services.llm_mock_client import MockLLMClient

    fixture_dir = Path("backend/tests/fixtures/llm_mocks")
    a = _A(llm=LLMService(client=MockLLMClient.from_fixture_dir(fixture_dir)))
    with pytest.raises(NotImplementedError, match="v0.5"):
        a.dispatch_subagent(name="critic", state=_make_state())
