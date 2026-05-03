"""Unit test for LLMService.chat schema= accepting Pydantic class (v0.8.2)."""

from __future__ import annotations

from typing import Any

import pytest
from app.services.llm_response import LLMResponse
from app.services.llm_service import LLMService
from app.services.openai_client import _RawClientResponse
from pydantic import BaseModel


@pytest.fixture(autouse=True)
def _allow_llm_service_in_unit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Override the LLM_MODE=none guard so LLMService can be constructed with a stub client.

    The unit conftest sets LLM_MODE=none to prevent accidental real LLM calls.
    This test file uses a fully-stub ChatClient (no real network), so the guard
    is safe to lift locally.
    """
    monkeypatch.delenv("LLM_MODE", raising=False)


class _StubBookSchema(BaseModel):
    title: str
    pages: int


class _StubChatClient:
    """Capture the schema arg passed to client.chat() for assertion."""

    def __init__(self, response_content: str) -> None:
        self.response_content = response_content
        self.captured_schema: Any = None

    def chat(self, prompt: str, model: str, schema: Any) -> _RawClientResponse:
        self.captured_schema = schema
        return _RawClientResponse(
            content=self.response_content,
            prompt_tokens=10,
            completion_tokens=20,
        )


@pytest.fixture
def stub_client_book() -> _StubChatClient:
    return _StubChatClient(response_content='{"title": "Hello", "pages": 42}')


def _build_service(client: _StubChatClient) -> LLMService:
    return LLMService(client=client, trace_service=None, cost_budget=None)


def test_dict_schema_legacy_path(stub_client_book: _StubChatClient) -> None:
    """传 dict 仍按老路径走,parsed=None。"""
    svc = _build_service(stub_client_book)
    schema_dict: dict[str, Any] = {"type": "object", "properties": {"title": {"type": "string"}}}
    r = svc.chat(prompt="hi", schema=schema_dict)
    assert isinstance(r, LLMResponse)
    assert stub_client_book.captured_schema == schema_dict
    assert r.parsed is None


def test_pydantic_class_auto_converted(stub_client_book: _StubChatClient) -> None:
    """传 Pydantic class:client 收到的 schema 是 model_json_schema() dict。"""
    svc = _build_service(stub_client_book)
    r = svc.chat(prompt="hi", schema=_StubBookSchema)
    assert isinstance(r, LLMResponse)
    assert stub_client_book.captured_schema == _StubBookSchema.model_json_schema()
    assert isinstance(r.parsed, _StubBookSchema)
    assert r.parsed.title == "Hello"
    assert r.parsed.pages == 42


def test_pydantic_class_invalid_content_raises() -> None:
    """LLM 返不合 schema 的 JSON → Pydantic ValidationError 抛出(让上游决定 retry)。"""
    bad_client = _StubChatClient(response_content='{"title": "Hello"}')  # 缺 pages
    from pydantic import ValidationError

    svc = _build_service(bad_client)
    with pytest.raises(ValidationError):
        svc.chat(prompt="hi", schema=_StubBookSchema)


def test_no_schema_unchanged(stub_client_book: _StubChatClient) -> None:
    """schema=None 走老路径,parsed=None,client 收到 None。"""
    svc = _build_service(stub_client_book)
    r = svc.chat(prompt="hi", schema=None)
    assert stub_client_book.captured_schema is None
    assert r.parsed is None
