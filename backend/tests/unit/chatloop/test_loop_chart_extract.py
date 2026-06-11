"""ToolLoop._extract_and_emit_charts — figures 抽出发 chart 事件 + 从输出剥离。"""

from __future__ import annotations

from typing import Any

import pytest

from app.agents.schemas import ToolResult
from app.chatloop.context import ContextDeps
from app.chatloop.events import LoopEvent, SeqCounter
from app.chatloop.loop import ToolLoop


def _make_loop(events: list[LoopEvent]) -> ToolLoop:
    async def _emit(ev: LoopEvent) -> None:
        events.append(ev)

    class _Hub:
        def schemas_for_llm(self) -> list[dict[str, Any]]:
            return []

        async def dispatch(self, calls: Any, state: Any) -> list[ToolResult]:  # pragma: no cover
            return []

    return ToolLoop(
        llm=object(),
        tool_hub=_Hub(),
        context_deps=ContextDeps(system_prompt="s"),
        emit=_emit,
        seq_counter=SeqCounter(),
    )


class _State:
    request_id = "req-1"
    step = 2


@pytest.mark.asyncio
async def test_figures_emitted_as_chart_events_and_stripped() -> None:
    events: list[LoopEvent] = []
    loop = _make_loop(events)
    fig_a = {"data": [{"type": "scatter"}], "layout": {}}
    fig_b = {"data": [{"type": "bar"}], "layout": {}}
    results = [
        ToolResult(
            tool_name="run_python",
            args={},
            success=True,
            output={"result": {"corr": 0.8}, "figures": [fig_a, fig_b]},
            latency_ms=5,
        ),
        ToolResult(
            tool_name="get_stock_quote",
            args={},
            success=True,
            output={"price": 100},
            latency_ms=5,
        ),
    ]

    await loop._extract_and_emit_charts(results, _State())  # type: ignore[arg-type]

    chart_events = [e for e in events if e.type == "chart"]
    assert len(chart_events) == 2
    assert chart_events[0].data["figure"] == fig_a
    assert chart_events[0].data["chart_id"] == "req-1-2-0-0"
    assert chart_events[1].data["chart_id"] == "req-1-2-0-1"
    # figures 已从 LLM 可见的 output 剥离,替换成计数标记
    assert "figures" not in results[0].output
    assert results[0].output["charts_rendered"] == 2
    assert results[0].output["result"] == {"corr": 0.8}
    # 无 figures 的工具输出不动
    assert results[1].output == {"price": 100}


@pytest.mark.asyncio
async def test_empty_figures_no_events_no_marker() -> None:
    events: list[LoopEvent] = []
    loop = _make_loop(events)
    results = [
        ToolResult(
            tool_name="run_python",
            args={},
            success=True,
            output={"result": 1, "figures": []},
            latency_ms=5,
        )
    ]
    await loop._extract_and_emit_charts(results, _State())  # type: ignore[arg-type]
    assert [e for e in events if e.type == "chart"] == []
    assert "figures" not in results[0].output
    assert "charts_rendered" not in results[0].output
