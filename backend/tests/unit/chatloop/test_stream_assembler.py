"""StreamAssembler — L0 单元测试,假 chunk 对象,无网络,无 I/O。

每个测试用 types.SimpleNamespace 构造 OpenAI 流式 chunk 的最小形状:
  chunk.choices  — list of choice
  choice.delta   — SimpleNamespace(content, reasoning_content, tool_calls)
  choice.finish_reason — str | None
  chunk.usage    — SimpleNamespace(prompt_tokens, completion_tokens,
                                   prompt_tokens_details) | None

注意:usage 通常在最后一个 choices=[] 的 chunk 里(stream_options include_usage)。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from app.services.openai_client import StreamAssembler

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_chunk(
    content: str | None = None,
    reasoning: str | None = None,
    tool_calls: list | None = None,
    finish_reason: str | None = None,
    usage=None,
) -> SimpleNamespace:
    """构造最小 OpenAI chunk。choices 空 + usage 非 None → usage-only chunk。"""
    if usage is not None and content is None and reasoning is None and tool_calls is None and finish_reason is None:
        # usage-only chunk: choices=[]
        return SimpleNamespace(choices=[], usage=usage)

    delta = SimpleNamespace(
        content=content,
        tool_calls=tool_calls,
    )
    # 注入 reasoning_content(getattr 链取)
    object.__setattr__(delta, "reasoning_content", reasoning)

    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice], usage=usage)


def _make_tool_call_fragment(
    index: int,
    id: str | None = None,
    name: str | None = None,
    arguments: str = "",
) -> SimpleNamespace:
    """构造 delta.tool_calls 里的单个 fragment。"""
    fn = SimpleNamespace(name=name, arguments=arguments)
    tc = SimpleNamespace(index=index, id=id, function=fn)
    return tc


def _make_usage(
    prompt_tokens: int = 20,
    completion_tokens: int = 10,
    cached_tokens: int = 5,
) -> SimpleNamespace:
    details = SimpleNamespace(cached_tokens=cached_tokens)
    return SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        prompt_tokens_details=details,
    )


# ---------------------------------------------------------------------------
# content 分片拼接
# ---------------------------------------------------------------------------


def test_content_chunks_accumulate_and_emit_deltas() -> None:
    """多片 content 产出 content delta 并最终拼合。"""
    asm = StreamAssembler()

    deltas1 = asm.feed(_make_chunk(content="茅台"))
    deltas2 = asm.feed(_make_chunk(content="今日"))
    deltas3 = asm.feed(_make_chunk(content="涨停"))

    # 每片均产一个 content delta
    assert len(deltas1) == 1 and deltas1[0].kind == "content" and deltas1[0].text == "茅台"
    assert len(deltas2) == 1 and deltas2[0].kind == "content" and deltas2[0].text == "今日"
    assert len(deltas3) == 1 and deltas3[0].kind == "content" and deltas3[0].text == "涨停"

    result = asm.result()
    assert result.content == "茅台今日涨停"


def test_empty_content_chunk_emits_no_delta() -> None:
    """content=None / '' 的 chunk 不产 delta。"""
    asm = StreamAssembler()
    deltas = asm.feed(_make_chunk(content=None))
    assert deltas == []
    deltas2 = asm.feed(_make_chunk(content=""))
    assert deltas2 == []


# ---------------------------------------------------------------------------
# reasoning_content
# ---------------------------------------------------------------------------


def test_reasoning_emits_reasoning_delta_not_content() -> None:
    """reasoning_content 流出 reasoning delta,不污染 content_parts。"""
    asm = StreamAssembler()

    rd = asm.feed(_make_chunk(reasoning="思考中"))
    assert len(rd) == 1
    assert rd[0].kind == "reasoning"
    assert rd[0].text == "思考中"

    # 再给一片 content
    asm.feed(_make_chunk(content="最终答案"))

    result = asm.result()
    assert result.content == "最终答案"  # reasoning 不污染 content


def test_reasoning_and_content_interleaved() -> None:
    """reasoning 与 content 混合流,各自独立聚合。"""
    asm = StreamAssembler()
    asm.feed(_make_chunk(reasoning="think1"))
    asm.feed(_make_chunk(content="answer"))
    asm.feed(_make_chunk(reasoning="think2"))

    result = asm.result()
    assert result.content == "answer"
    # reasoning_parts 存储但不进 content
    assert "think1" in asm.reasoning_parts
    assert "think2" in asm.reasoning_parts


# ---------------------------------------------------------------------------
# tool_calls 双工具分片拼接
# ---------------------------------------------------------------------------


def test_two_tools_assembled_by_index() -> None:
    """双工具按 index 分片,arguments 跨片半个 JSON 最终拼合;name 首片产 tool_call delta。"""
    asm = StreamAssembler()

    # index=0: id+name 首片
    tc0_first = _make_tool_call_fragment(index=0, id="call_0", name="get_price", arguments='{"ts')
    d0 = asm.feed(_make_chunk(tool_calls=[tc0_first]))
    assert len(d0) == 1
    assert d0[0].kind == "tool_call"
    assert d0[0].tool_name == "get_price"

    # index=1: id+name 首片
    tc1_first = _make_tool_call_fragment(index=1, id="call_1", name="get_eps", arguments='{"sym')
    d1 = asm.feed(_make_chunk(tool_calls=[tc1_first]))
    assert len(d1) == 1
    assert d1[0].kind == "tool_call"
    assert d1[0].tool_name == "get_eps"

    # index=0: arguments 续片(no id/name)
    tc0_cont = _make_tool_call_fragment(index=0, id=None, name=None, arguments='_code":"600519.SH"}')
    d0c = asm.feed(_make_chunk(tool_calls=[tc0_cont]))
    # 续片不产 tool_call delta(name 已记录)
    assert d0c == []

    # index=1: arguments 续片
    tc1_cont = _make_tool_call_fragment(index=1, id=None, name=None, arguments='bol":"AAPL"}')
    asm.feed(_make_chunk(tool_calls=[tc1_cont]))

    result = asm.result()
    assert len(result.tool_calls) == 2

    tc_by_name = {tc.name: tc for tc in result.tool_calls}
    assert tc_by_name["get_price"].id == "call_0"
    assert tc_by_name["get_price"].arguments == '{"ts_code":"600519.SH"}'
    assert tc_by_name["get_eps"].id == "call_1"
    assert tc_by_name["get_eps"].arguments == '{"symbol":"AAPL"}'


def test_tool_call_id_defaults_when_missing() -> None:
    """id 缺失时 StepToolCall.id 回退为 call_{index}。"""
    asm = StreamAssembler()
    tc = _make_tool_call_fragment(index=0, id=None, name="search", arguments='{"q":"茅台"}')
    asm.feed(_make_chunk(tool_calls=[tc]))

    result = asm.result()
    assert result.tool_calls[0].id == "call_0"


def test_empty_string_name_id_fragments_do_not_clobber() -> None:
    """qwen 流式实测(L2 cassette):续片把 id/name 置为空串 "" 而非省略/null。

    回归守护:空串续片不得覆盖首片已拿到的真实 id/name —— 否则下游
    ChatLoopAgent._extract_tool_calls 抽到空工具名(本 task 录制时实测到 ['','','',''])。
    """
    asm = StreamAssembler()

    # 首片:真实 id+name + arguments 开头
    first = _make_tool_call_fragment(
        index=0, id="call_abc", name="get_stock_quote", arguments=""
    )
    d0 = asm.feed(_make_chunk(tool_calls=[first]))
    assert len(d0) == 1 and d0[0].tool_name == "get_stock_quote"

    # 续片:id="" name="" (qwen 真实形状),只带 arguments 片段
    for frag_args in ('{', '"ts_code": "600', '519.', 'SH"}'):
        cont = _make_tool_call_fragment(index=0, id="", name="", arguments=frag_args)
        dc = asm.feed(_make_chunk(tool_calls=[cont]))
        # 续片不得再产 tool_call delta(name 已记录)
        assert dc == []

    result = asm.result()
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].id == "call_abc"
    assert result.tool_calls[0].name == "get_stock_quote"
    assert result.tool_calls[0].arguments == '{"ts_code": "600519.SH"}'


# ---------------------------------------------------------------------------
# usage / cached_tokens
# ---------------------------------------------------------------------------


def test_usage_chunk_captured_and_cached_tokens_extracted() -> None:
    """usage 末片到达,cached_tokens 正确提取,结果 tokens 字段填充。"""
    asm = StreamAssembler()
    asm.feed(_make_chunk(content="答案"))

    usage = _make_usage(prompt_tokens=50, completion_tokens=20, cached_tokens=30)
    asm.feed(_make_chunk(usage=usage))

    result = asm.result()
    assert result.prompt_tokens == 50
    assert result.completion_tokens == 20
    assert result.cached_tokens == 30


def test_usage_missing_tokens_all_zero() -> None:
    """usage 缺失时 tokens 全 0。"""
    asm = StreamAssembler()
    asm.feed(_make_chunk(content="答案"))

    result = asm.result()
    assert result.prompt_tokens == 0
    assert result.completion_tokens == 0
    assert result.cached_tokens == 0


def test_usage_missing_cached_tokens_details_zero() -> None:
    """usage 有但 prompt_tokens_details 缺失 → cached_tokens=0。"""
    asm = StreamAssembler()
    usage = SimpleNamespace(
        prompt_tokens=10,
        completion_tokens=5,
        prompt_tokens_details=None,
    )
    asm.feed(_make_chunk(usage=usage))

    result = asm.result()
    assert result.cached_tokens == 0
    assert result.prompt_tokens == 10


# ---------------------------------------------------------------------------
# finish_reason
# ---------------------------------------------------------------------------


def test_finish_reason_recorded() -> None:
    """finish_reason 在 chunk 里到达时被记录到 asm.finish_reason 和 result。"""
    asm = StreamAssembler()
    asm.feed(_make_chunk(content="ok", finish_reason="stop"))

    result = asm.result()
    assert asm.finish_reason == "stop"
    assert result.finish_reason == "stop"


def test_finish_reason_tool_calls() -> None:
    """finish_reason=tool_calls 正确记录。"""
    asm = StreamAssembler()
    tc = _make_tool_call_fragment(index=0, id="c1", name="fn", arguments="{}")
    asm.feed(_make_chunk(tool_calls=[tc], finish_reason="tool_calls"))

    result = asm.result()
    assert result.finish_reason == "tool_calls"


# ---------------------------------------------------------------------------
# cost_cny 透传
# ---------------------------------------------------------------------------


def test_result_cost_passed_through() -> None:
    """result(cost_cny=X) 直接进入 StepResult.cost_cny。"""
    asm = StreamAssembler()
    asm.feed(_make_chunk(content="x"))
    result = asm.result(cost_cny=0.042)
    assert result.cost_cny == pytest.approx(0.042)


# ---------------------------------------------------------------------------
# function=None 空保护
# ---------------------------------------------------------------------------


def test_tool_call_fragment_function_none_no_error() -> None:
    """首片 function=None(某些模型只带 index/type) → 不抛 AttributeError。

    后续片带 function.name/arguments → 正常拼出完整 tool_call。
    """
    asm = StreamAssembler()

    # 首片:function=None,只携带 id 和 index
    first_frag = SimpleNamespace(index=0, id="c1", function=None)
    d0 = asm.feed(_make_chunk(tool_calls=[first_frag]))
    # 首片 function=None → 无 name → 不产 tool_call delta
    assert d0 == []

    # 后续片:携带 name + arguments
    second_frag = SimpleNamespace(
        index=0,
        id=None,
        function=SimpleNamespace(name="get_price", arguments='{"code":"600519"}'),
    )
    d1 = asm.feed(_make_chunk(tool_calls=[second_frag]))
    # name 首次到达 → 产 tool_call delta
    assert len(d1) == 1
    assert d1[0].kind == "tool_call"
    assert d1[0].tool_name == "get_price"

    result = asm.result()
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].id == "c1"
    assert result.tool_calls[0].name == "get_price"
    assert result.tool_calls[0].arguments == '{"code":"600519"}'
