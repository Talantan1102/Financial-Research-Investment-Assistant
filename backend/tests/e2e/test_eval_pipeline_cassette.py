"""L2 — eval pipeline against real DashScope endpoint, replayed via cassette.

This proves the entire pipeline (SUT call → trace → judge call → recorder)
works against the real LLM behavior. Slow on first record, fast on replay.
"""

import contextlib
import os
from typing import Any

import pytest
from app.services.eval_models import GoldenCase
from app.services.eval_recorder import EvalRecorder
from app.services.eval_runner import EvalRunner
from app.services.judge import Judge
from app.services.llm_service import LLMService
from app.services.trace_service import TraceService
from openai import OpenAI


def _strip_dashscope_response_headers(response: dict[str, Any]) -> dict[str, Any]:
    """Remove DashScope-specific response headers before recording.

    Headers like ``x-dashscope-call-gateway`` contain the substring
    ``dashscope-``, which the check_cassette_sanitize.py script flags as a
    potential credential leak. Strip them at recording time.
    """
    headers = response.get("headers", {})
    response["headers"] = {k: v for k, v in headers.items() if "dashscope" not in k.lower()}
    return response


@pytest.fixture(scope="module")
def vcr_config() -> dict:
    """Override module-level VCR config: drop body from match criteria.

    The judge prompt body includes ``total_latency_ms`` from the trace
    service, which is measured at real time and will differ between the
    recording run and replay. Without this override, the second cassette
    interaction (the judge call) would never match on replay because the
    trace latency embedded in the judge prompt changes each run.

    Requests are matched in recording order (method+scheme+host+port+path),
    which is deterministic for this two-request pipeline test.
    """
    return {
        "filter_headers": [
            "authorization",
            "x-dashscope-api-key",
            "x-api-key",
            "openai-organization",
        ],
        "filter_post_data_parameters": [],
        "decode_compressed_response": True,
        "record_mode": os.environ.get("VCR_RECORD_MODE", "none"),
        "match_on": ["method", "scheme", "host", "port", "path"],
        "before_record_response": _strip_dashscope_response_headers,
    }


class _Adapter:
    """Same adapter pattern as Plan B's L2 cassette test."""

    def __init__(self, client: OpenAI) -> None:
        self._c = client

    def chat(self, prompt, model, schema):  # noqa: ANN001
        r = self._c.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
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
def real_adapter() -> _Adapter:
    return _Adapter(
        OpenAI(
            api_key=os.environ.get("DASHSCOPE_API_KEY", "fake-for-replay"),
            base_url=os.environ.get(
                "DASHSCOPE_BASE_URL",
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
            ),
        )
    )


@pytest.mark.vcr
def test_one_case_real_llm_real_judge(
    real_adapter: _Adapter,
    db_session,
) -> None:
    trace = TraceService(session_factory=lambda: contextlib.nullcontext(db_session))
    recorder = EvalRecorder(session_factory=lambda: contextlib.nullcontext(db_session))

    sut = LLMService(client=real_adapter, trace_service=trace)
    judge_llm = LLMService(client=real_adapter)
    judge = Judge(llm=judge_llm, judge_tier="balanced")
    runner = EvalRunner(sut=sut, judge=judge, trace_service=trace, recorder=recorder)

    case = GoldenCase(
        case_id="cassette-1",
        category="single_tool_call",
        user_input="贵州茅台的股票代码是什么?用一句话回答。",
        expected_behavior={"response_must_contain": ["600519"]},
        metadata={"added_by": "plan-c-l2", "added_at": "2026-04-30", "tags": ["v0"]},
    )

    result = runner.run_one(case)
    assert result.case_id == "cassette-1"
    assert result.scores.factuality is not None
    assert result.judge_cost_cny >= 0
