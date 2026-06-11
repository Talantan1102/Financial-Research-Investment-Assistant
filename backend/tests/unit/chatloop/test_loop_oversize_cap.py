"""② ToolLoop 输出整形 — 超大工具结果截断(只截能取回的)。"""

from __future__ import annotations

from typing import Any

import pytest

from app.agents.schemas import ToolResult
from app.chatloop.context import ContextDeps
from app.chatloop.events import LoopEvent, SeqCounter
from app.chatloop.loop import ToolLoop
from app.chatloop.state import ChatLoopState

pytestmark = pytest.mark.asyncio


def _loop(events: list[LoopEvent], threshold: int = 4000) -> ToolLoop:
    async def _emit(ev: LoopEvent) -> None:
        events.append(ev)

    class _Hub:
        def schemas_for_llm(self) -> list[dict[str, Any]]:
            return []

        async def dispatch(self, calls: Any, state: Any) -> list[ToolResult]:  # pragma: no cover
            return []

    deps = ContextDeps(system_prompt="s", oversize_result_char_threshold=threshold)
    return ToolLoop(
        llm=object(), tool_hub=_Hub(), context_deps=deps,
        emit=_emit, seq_counter=SeqCounter(),
    )


def _state() -> ChatLoopState:
    return ChatLoopState(user_id="u", session_id="s", request_id="req-1", messages=[])


async def test_oversize_with_ref_is_truncated() -> None:
    events: list[LoopEvent] = []
    loop = _loop(events, threshold=200)
    st = _state()
    args = {"q": "白酒政策"}
    big = {"chunks": ["政策正文" * 200]}  # 远超 200 字
    st.ledger.record(step=1, tool_name="query_kb", args=args,
                     digest="d", success=True, cache_key="u:query_kb:abc")
    results = [ToolResult(tool_name="query_kb", args=args, success=True, output=big, latency_ms=5)]

    await loop._extract_and_emit_charts(results, st)

    out = results[0].output
    assert out["ref"] == "u:query_kb:abc"
    assert "truncated_digest" in out and "read_cached_result" in out["note"]
    assert out["original_chars"] > 200
    assert "chunks" not in out  # 原文已换出


async def test_oversize_without_ref_kept_intact() -> None:
    events: list[LoopEvent] = []
    loop = _loop(events, threshold=200)
    st = _state()
    big = {"text": "技能方法论" * 200}
    # ledger 无对应成功条目 → 无 ref → 不截(安全不变量)
    results = [ToolResult(tool_name="load_skill", args={"name": "x"}, success=True,
                          output=big, latency_ms=5)]
    await loop._extract_and_emit_charts(results, st)
    assert results[0].output == big  # 原样留存


async def test_small_result_untouched() -> None:
    events: list[LoopEvent] = []
    loop = _loop(events, threshold=4000)
    st = _state()
    args = {"ts": "x"}
    st.ledger.record(step=1, tool_name="quote", args=args, digest="d",
                     success=True, cache_key="k")
    results = [ToolResult(tool_name="quote", args=args, success=True,
                          output={"price": 100}, latency_ms=5)]
    await loop._extract_and_emit_charts(results, st)
    assert results[0].output == {"price": 100}


async def test_figures_not_counted_toward_size() -> None:
    events: list[LoopEvent] = []
    loop = _loop(events, threshold=200)
    st = _state()
    args = {"ts": "x"}
    st.ledger.record(step=1, tool_name="run_python", args=args, digest="d",
                     success=True, cache_key="k")
    # 正文小、figures 大:剥 figures 后不应触发截断
    big_fig = {"data": [{"x": list(range(500))}], "layout": {}}
    results = [ToolResult(tool_name="run_python", args=args, success=True,
                          output={"result": {"corr": 0.8}, "figures": [big_fig]}, latency_ms=5)]
    await loop._extract_and_emit_charts(results, st)
    assert results[0].output["result"] == {"corr": 0.8}
    assert results[0].output["charts_rendered"] == 1
    assert "truncated_digest" not in results[0].output
