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
        llm=object(),
        tool_hub=_Hub(),
        context_deps=deps,
        emit=_emit,
        seq_counter=SeqCounter(),
    )


def _state() -> ChatLoopState:
    return ChatLoopState(user_id="u", session_id="s", request_id="req-1", messages=[])


async def test_oversize_with_ref_is_truncated() -> None:
    events: list[LoopEvent] = []
    loop = _loop(events, threshold=200)
    st = _state()
    args = {"q": "白酒政策"}
    big = {"chunks": ["政策正文" * 200]}  # 远超 200 字
    st.ledger.record(
        step=1,
        tool_name="query_kb",
        args=args,
        digest="d",
        success=True,
        cache_key="u:query_kb:abc",
    )
    results = [ToolResult(tool_name="query_kb", args=args, success=True, output=big, latency_ms=5)]

    await loop._extract_and_emit_charts(results, st)

    out = results[0].output
    assert isinstance(out, dict)
    assert out["ref"] == "u:query_kb:abc"
    assert "truncated_digest" in out and "read_cached_result" in out["note"]
    assert "data_refs" in out["note"]  # 计算优先走 data_refs(大数据一次灌沙箱,不分页耗预算)
    assert out["original_chars"] > 200
    assert "chunks" not in out  # 原文已换出


async def test_oversize_without_ref_kept_intact() -> None:
    events: list[LoopEvent] = []
    loop = _loop(events, threshold=200)
    st = _state()
    big = {"text": "技能方法论" * 200}
    # ledger 无对应成功条目 → 无 ref → 不截(安全不变量)
    results = [
        ToolResult(
            tool_name="load_skill", args={"name": "x"}, success=True, output=big, latency_ms=5
        )
    ]
    await loop._extract_and_emit_charts(results, st)
    assert results[0].output == big  # 原样留存


async def test_small_result_untouched() -> None:
    events: list[LoopEvent] = []
    loop = _loop(events, threshold=4000)
    st = _state()
    args = {"ts": "x"}
    st.ledger.record(step=1, tool_name="quote", args=args, digest="d", success=True, cache_key="k")
    results = [
        ToolResult(tool_name="quote", args=args, success=True, output={"price": 100}, latency_ms=5)
    ]
    await loop._extract_and_emit_charts(results, st)
    assert results[0].output == {"price": 100}


async def test_figures_not_counted_toward_size() -> None:
    events: list[LoopEvent] = []
    loop = _loop(events, threshold=200)
    st = _state()
    args = {"ts": "x"}
    st.ledger.record(
        step=1, tool_name="run_python", args=args, digest="d", success=True, cache_key="k"
    )
    # 正文小、figures 大:剥 figures 后不应触发截断
    big_fig = {"data": [{"x": list(range(500))}], "layout": {}}
    results = [
        ToolResult(
            tool_name="run_python",
            args=args,
            success=True,
            output={"result": {"corr": 0.8}, "figures": [big_fig]},
            latency_ms=5,
        )
    ]
    await loop._extract_and_emit_charts(results, st)
    out = results[0].output
    assert isinstance(out, dict)
    assert out["result"] == {"corr": 0.8}
    assert out["charts_rendered"] == 1
    assert "truncated_digest" not in out


async def test_default_oversize_threshold_is_24000() -> None:
    # ① 默认阈值抬到 24000(一年单序列 ~15k 字不再误截)
    assert ContextDeps(system_prompt="s").oversize_result_char_threshold == 24000


async def test_midsize_series_not_truncated_at_default() -> None:
    # 介于旧阈值(4000)与新阈值(24000)之间的结果,在默认阈值下不截断
    events: list[LoopEvent] = []
    loop = _loop(events, threshold=ContextDeps(system_prompt="s").oversize_result_char_threshold)
    st = _state()
    args = {"ts_code": "600519.SH"}
    st.ledger.record(
        step=1,
        tool_name="get_daily",
        args=args,
        digest="d",
        success=True,
        cache_key="u::get_daily::k",
    )
    series = {"close": list(range(2000))}  # 序列化约 1 万字,> 4000 但 < 24000
    results = [
        ToolResult(tool_name="get_daily", args=args, success=True, output=series, latency_ms=5)
    ]
    await loop._extract_and_emit_charts(results, st)
    assert "truncated_digest" not in results[0].output  # 默认阈值下不截


async def test_oversize_with_summary_preserves_summary() -> None:
    events: list[LoopEvent] = []
    loop = _loop(events, threshold=200)
    st = _state()
    args = {"ts_code": "600519.SH", "start": "20230101", "end": "20260101"}
    summary = {
        "ts_code": "600519.SH",
        "count": 725,
        "date_start": "20230101",
        "date_end": "20260101",
        "first_close": 1678.0,
        "last_close": 1502.0,
        "period_high": 1900.0,
        "period_low": 1402.0,
    }
    big = {"summary": summary, "close": list(range(2000))}  # 远超 200 字
    st.ledger.record(
        step=1,
        tool_name="get_daily",
        args=args,
        digest="d",
        success=True,
        cache_key="u::get_daily::abc",
    )
    results = [
        ToolResult(tool_name="get_daily", args=args, success=True, output=big, latency_ms=5)
    ]
    await loop._extract_and_emit_charts(results, st)
    out = results[0].output
    assert isinstance(out, dict)
    assert out["summary"] == summary  # 信息卡存活
    assert out["ref"] == "u::get_daily::abc"
    assert "data_refs" in out["note"]
    assert "truncated_digest" not in out  # 有 summary 就不用粗暴 600 字 digest
    assert "close" not in out  # 完整数组换出
