"""L2 — LLMService against the real DashScope-compatible endpoint, replayed
via cassette. The cassette is committed to git after Task 11 step 3 records
it for the first time. Subsequent runs are pure replay (no network).
"""

import os

import pytest
from app.services.llm_response import LLMResponse  # noqa: TCH001
from app.services.llm_service import LLMService
from openai import OpenAI


class _OpenAIClientAdapter:
    """Adapts openai.OpenAI to the ChatClient protocol used by LLMService."""

    def __init__(self, client: OpenAI) -> None:
        self._c = client

    def chat(self, prompt, model, schema):  # noqa: ANN001
        r = self._c.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=64,
        )
        return _Raw(
            content=r.choices[0].message.content or "",
            prompt_tokens=r.usage.prompt_tokens if r.usage else 0,
            completion_tokens=r.usage.completion_tokens if r.usage else 0,
        )


class _Raw:
    def __init__(self, content: str, prompt_tokens: int, completion_tokens: int) -> None:
        self.content = content
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


@pytest.fixture
def real_openai_adapter() -> _OpenAIClientAdapter:
    """Real client. Under cassette mode the HTTP call is intercepted by
    pytest-recording — no live traffic. Under VCR_RECORD_MODE=once the call
    goes out and gets recorded.
    """
    return _OpenAIClientAdapter(
        OpenAI(
            api_key=os.environ.get("DASHSCOPE_API_KEY", "fake-for-replay"),
            base_url=os.environ.get(
                "DASHSCOPE_BASE_URL",
                # Must match the host recorded in the cassette so VCR replay
                # works without DASHSCOPE_BASE_URL set (e.g. on CI).
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
            ),
        )
    )


@pytest.mark.vcr
def test_chat_fast_tier_returns_response(
    real_openai_adapter: _OpenAIClientAdapter,
) -> None:
    svc = LLMService(client=real_openai_adapter)
    r: LLMResponse = svc.chat(prompt="Say hi in one word.", tier="fast")
    assert r.tier == "fast"
    assert r.model == "deepseek-v4-flash"
    assert len(r.content) > 0
    assert r.prompt_tokens > 0
