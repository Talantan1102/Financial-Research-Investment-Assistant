"""Unit test: build_llm_service_from_env 只在 LANGSMITH_TRACING 开启时用 wrap_openai 包装 client (P0)。

守门逻辑验证:
- 开(true/1/yes…)→ wrap_openai 被调用,收到的是原始 OpenAI client;
- 关(unset/false/0/no)→ wrap_openai 绝不被调用(零开销)。
全程假 client,无真网络。
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from app.services import openai_client
from app.services.openai_client import build_llm_service_from_env


@pytest.fixture(autouse=True)
def _allow_llm_service_in_unit(monkeypatch: pytest.MonkeyPatch) -> None:
    # unit conftest 设 LLM_MODE=none 防真调用;本测试全程假 client,解除守卫即可构造 LLMService。
    monkeypatch.delenv("LLM_MODE", raising=False)


class _FakeOpenAI:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs


def _recording_wrap(calls: list[object]) -> Callable[[object], str]:
    """假 wrap_openai:记录调用入参,返回哨兵字符串。"""

    def _wrap(client: object) -> str:
        calls.append(client)
        return "WRAPPED"

    return _wrap


@pytest.mark.parametrize("tracing_value", ["true", "1", "yes", "TRUE", " true "])
def test_wrap_openai_called_when_tracing_on(
    monkeypatch: pytest.MonkeyPatch, tracing_value: str
) -> None:
    monkeypatch.setenv("LANGSMITH_TRACING", tracing_value)
    fake_raw = _FakeOpenAI()
    wrap_calls: list[object] = []

    monkeypatch.setattr(openai_client, "OpenAI", lambda **kw: fake_raw)
    monkeypatch.setattr("langsmith.wrappers.wrap_openai", _recording_wrap(wrap_calls))

    build_llm_service_from_env()

    # wrap_openai 被调用一次,且收到的就是原始 client
    assert wrap_calls == [fake_raw]


@pytest.mark.parametrize("tracing_value", ["", "false", "0", "no"])
def test_wrap_openai_not_called_when_tracing_off(
    monkeypatch: pytest.MonkeyPatch, tracing_value: str
) -> None:
    if tracing_value == "":
        monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    else:
        monkeypatch.setenv("LANGSMITH_TRACING", tracing_value)

    wrap_calls: list[object] = []
    monkeypatch.setattr(openai_client, "OpenAI", lambda **kw: _FakeOpenAI())
    monkeypatch.setattr("langsmith.wrappers.wrap_openai", _recording_wrap(wrap_calls))

    build_llm_service_from_env()

    # 关闭时绝不调用 wrap_openai(零开销,基础安装无 langsmith 也不受影响)
    assert wrap_calls == []
