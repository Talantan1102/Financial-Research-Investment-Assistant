"""LLMService 模型覆盖口子:给 model 用 model(映射 dashscope id),不给走 tier,不在清单 raise。"""

from __future__ import annotations

from typing import Any

import pytest
from app.services.llm_service import LLMService
from app.services.openai_client import _RawClientResponse


@pytest.fixture(autouse=True)
def _allow_construction(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_MODE", raising=False)


class _RecordingClient:
    def __init__(self) -> None:
        self.models: list[str] = []

    def chat(self, prompt: str, model: str, schema: Any) -> _RawClientResponse:
        self.models.append(model)
        return _RawClientResponse(content="hi", prompt_tokens=1, completion_tokens=1)


class _NullTrace:
    def write_span(self, span: Any) -> None:  # noqa: D401
        pass


def _svc(client: _RecordingClient) -> LLMService:
    return LLMService(client=client, trace_service=_NullTrace(), cost_budget=None)  # type: ignore[arg-type]


def test_model_override_maps_key_to_dashscope_id() -> None:
    c = _RecordingClient()
    _svc(c).chat(prompt="hi", tier="fast", request_id="r1", model="qwen2.5-7b")
    assert c.models[-1] == "qwen2.5-7b-instruct"  # registry key → dashscope id


def test_no_model_falls_back_to_tier() -> None:
    c = _RecordingClient()
    _svc(c).chat(prompt="hi", tier="fast", request_id="r2")
    assert c.models[-1] == "deepseek-v4-flash"  # tier → V0_DEFAULT_MODEL


def test_unknown_model_raises() -> None:
    with pytest.raises(ValueError):
        _svc(_RecordingClient()).chat(prompt="hi", tier="fast", request_id="r3", model="gpt-4")
