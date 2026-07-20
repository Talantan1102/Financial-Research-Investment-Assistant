"""Cassette acceptance for the production chat executor boundary."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

CHATLOOP_CASSETTE_DIR = (
    Path(__file__).resolve().parents[1] / "fixtures" / "cassettes" / "test_chatloop_cassette"
)


def _load_smoke_module() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "scripts" / "smoke_run_chat.py"
    spec = importlib.util.spec_from_file_location("run_chat_smoke_acceptance", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_live_smoke_module_is_importable_and_never_logs_prompt_or_credentials() -> None:
    result = _load_smoke_module().sanitize_result(
        run_id="run-id",
        session_id="session-id",
        status="completed",
        elapsed_seconds=1.25,
        model_route="dashscope/qwen",
    )
    rendered = repr(result)
    assert result["run_id"] == "run-id"
    assert "prompt" not in rendered.lower()
    assert "api_key" not in rendered.lower()


@pytest.fixture(scope="module")
def vcr_cassette_dir() -> str:
    """Reuse the committed recording for the identical production-loop request."""
    return str(CHATLOOP_CASSETTE_DIR)


@pytest.fixture(scope="module")
def vcr_config() -> dict[str, Any]:
    return {
        "filter_headers": [
            "authorization",
            "x-dashscope-api-key",
            "x-api-key",
            "openai-organization",
        ],
        "decode_compressed_response": True,
        "record_mode": os.environ.get("VCR_RECORD_MODE", "none"),
        "match_on": ["method", "scheme", "host", "port", "path"],
    }


@pytest.mark.vcr
@pytest.mark.default_cassette("test_chatloop_single_tool")
@pytest.mark.asyncio
async def test_run_chat_executor_cassette_completes_with_nonempty_answer() -> None:
    """Replay a real model/tool loop used by the production Run chat executor."""
    from tests.e2e.test_chatloop_cassette import _build_chatloop_agent

    result = await _build_chatloop_agent().run(
        "贵州茅台现在股价多少?", request_id="cassette-single-tool"
    )
    assert result.response_text.strip()
    assert "get_stock_quote" in [call.tool_name for call in result.tool_calls]
