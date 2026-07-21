"""Cassette acceptance for the production chat executor boundary."""

from __future__ import annotations

import asyncio
import copy
import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

CHATLOOP_CASSETTE_DIR = (
    Path(__file__).resolve().parents[1] / "fixtures" / "cassettes" / "test_chatloop_cassette"
)


def test_cassette_acceptance_does_not_delegate_to_legacy_agent_harness() -> None:
    source = Path(__file__).read_text(encoding="utf-8")
    legacy_builder_name = "_build_chatloop" + "_agent"
    assert legacy_builder_name not in source


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


def test_live_smoke_uses_the_worker_model_route_resolver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MOCK_TUSHARE_MODEL", "canonical-worker-model")
    monkeypatch.setenv("RUN_CHAT_MODEL_ROUTE", "wrong/override")
    monkeypatch.setenv("LLM_PROVIDER", "wrong-provider")
    monkeypatch.setenv("LLM_MODEL", "wrong-model")
    monkeypatch.setenv("DASHSCOPE_MODEL", "also-wrong")

    assert _load_smoke_module()._configured_model_route() == ("dashscope/canonical-worker-model")


def test_live_smoke_cli_resolves_backend_package_from_repo_root() -> None:
    path = Path(__file__).resolve().parents[2] / "scripts" / "smoke_run_chat.py"
    environment = os.environ.copy()
    environment.pop("RUN_CHAT_TENANT_ID", None)
    environment.pop("RUN_CHAT_AUTH_TOKEN", None)
    environment.pop("POSTGRES_PASSWORD", None)

    completed = subprocess.run(
        [sys.executable, str(path)],
        cwd=Path(__file__).resolve().parents[3],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 1
    assert completed.stderr == ""
    assert '"error": "KeyError"' in completed.stdout


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
    """Replay real DashScope I/O through the production Run executor adapter."""
    from app.chatloop.control_tools import OfferDeepResearchTool
    from app.chatloop.gates import GateConfig
    from app.chatloop.run_executor import ChatRunExecutor, CompletedResult, ExecuteChatRun
    from app.chatloop.system_prompt import CHAT_SYSTEM_PROMPT
    from app.chatloop.tool_docs import CORE_TOOLS, DEFERRED_TOOLS
    from app.chatloop.tool_hub import ToolHub
    from app.services.llm_identity import resolve_llm_identity_from_env
    from app.services.openai_client import build_llm_service_from_env

    from tests.e2e.test_chatloop_cassette import _FAKE_RESULTS, _FakeTool, _NullTrace

    class RecordingLLM:
        def __init__(self, inner: Any) -> None:
            self.inner = inner
            self.requests: list[list[dict[str, Any]]] = []

        async def stream_step(self, **kwargs: Any) -> Any:
            self.requests.append(copy.deepcopy(kwargs["messages"]))
            return await self.inner.stream_step(**kwargs)

    llm = RecordingLLM(build_llm_service_from_env(trace_service=_NullTrace()))  # type: ignore[arg-type]
    fake_names = [name for name in (*CORE_TOOLS, *DEFERRED_TOOLS) if name != "offer_deep_research"]

    def build_components(emit: Any, seq_counter: Any) -> Any:
        hub = ToolHub(emit=emit, seq_counter=seq_counter)
        hub.register_inprocess([_FakeTool(name, _FAKE_RESULTS[name]) for name in fake_names])
        hub.register_inprocess([OfferDeepResearchTool()])
        return SimpleNamespace(
            llm=llm,
            tool_hub=hub,
            gate_cfg=GateConfig(),
            skill_listing="",
            system_prompt=CHAT_SYSTEM_PROMPT,
        )

    published: list[Any] = []

    async def capture_event(event: Any) -> None:
        published.append(event)

    provider, model = resolve_llm_identity_from_env()
    executor = ChatRunExecutor(
        components_factory=build_components,
        event_sink=capture_event,
        cancel_event=asyncio.Event(),
        user_id="cassette-user",
        continuation_secret=b"c" * 32,
        provider=provider,
        model=model,
    )
    run_id, attempt_id, session_id = uuid4(), uuid4(), uuid4()
    history = (
        {"role": "user", "content": "history-user-marker"},
        {"role": "assistant", "content": "history-assistant-marker"},
    )
    prompt = "贵州茅台现在股价多少?"
    result = await executor.execute(
        ExecuteChatRun(run_id, attempt_id, session_id, prompt, history, None, uuid4())
    )

    assert isinstance(result, CompletedResult)
    assert (result.run_id, result.attempt_id, result.session_id) == (
        run_id,
        attempt_id,
        session_id,
    )
    assert result.final_text.strip()
    assert "1700" in result.final_text.replace(",", "")
    assert result.usage.provider == provider
    assert result.usage.model == model
    assert result.usage.input_tokens > 0
    assert result.usage.output_tokens > 0
    assert result.usage.total_tokens == result.usage.input_tokens + result.usage.output_tokens

    quote = next(tool for tool in result.tools if tool.tool_name == "get_stock_quote")
    assert quote.status == "completed"
    assert quote.tool_call_id
    assert quote.request

    assert published == list(result.events)
    assert [event.seq for event in result.events] == sorted(event.seq for event in result.events)
    assert len({event.seq for event in result.events}) == len(result.events)
    assert {event.kind for event in result.events} >= {
        "step_start",
        "tool_call",
        "tool_start",
        "tool_end",
        "cost_update",
        "done",
    }
    assert all((event.run_id, event.attempt_id) == (run_id, attempt_id) for event in result.events)

    assert llm.requests
    first_messages = llm.requests[0]
    history_user_index = first_messages.index(history[0])
    history_assistant_index = first_messages.index(history[1])
    prompt_index = first_messages.index({"role": "user", "content": prompt})
    assert history_user_index < history_assistant_index < prompt_index
