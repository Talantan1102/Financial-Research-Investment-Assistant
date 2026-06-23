"""非 deepseek 模型兼容垫片:qwen3 关思考 + tool_call args 合法化(承 2026-06-18 排查)。

追加:StreamAssembler reasoning 字段聚合测试(承 2026-06-22 think 进轨迹 feature)。
"""

from typing import Any

from app.services.openai_client import StreamAssembler, _extra_body_for, _sanitize_tool_args


def test_extra_body_qwen3_disables_thinking() -> None:
    assert _extra_body_for("qwen3-8b") == {"enable_thinking": False}
    assert _extra_body_for("qwen3-32b") == {"enable_thinking": False}
    assert _extra_body_for("deepseek-v4-flash") == {}
    assert _extra_body_for("qwen-max") == {}


def test_sanitize_empty_and_invalid_args_to_empty_object() -> None:
    msgs: list[dict[str, Any]] = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "tool_calls": [
                {"id": "a", "type": "function", "function": {"name": "f", "arguments": ""}},
                {"id": "b", "type": "function", "function": {"name": "g", "arguments": "not-json"}},
                {"id": "c", "type": "function", "function": {"name": "h", "arguments": '{"x":1}'}},
            ],
        },
    ]
    out = _sanitize_tool_args(msgs)
    tcs = out[1]["tool_calls"]
    assert tcs[0]["function"]["arguments"] == "{}"  # 空串兜底
    assert tcs[1]["function"]["arguments"] == "{}"  # 坏 JSON 兜底
    assert tcs[2]["function"]["arguments"] == '{"x":1}'  # 合法保留
    assert out[0] == msgs[0]  # 非 tool_calls 消息原样


def test_sanitize_leaves_non_tool_messages() -> None:
    msgs = [{"role": "user", "content": "hi"}]
    assert _sanitize_tool_args(msgs) == msgs


# ---------------------------------------------------------------------------
# StreamAssembler — reasoning 字段聚合(承 2026-06-22 think 进轨迹 feature)
# ---------------------------------------------------------------------------


class _FakeDelta:
    """轻量伪 delta — StreamAssembler.feed 只访问 .reasoning_content / .content / .tool_calls。"""

    def __init__(
        self,
        content: str | None = None,
        reasoning_content: str | None = None,
        tool_calls: list | None = None,
    ) -> None:
        self.content = content
        self.reasoning_content = reasoning_content
        self.tool_calls = tool_calls or []


class _FakeChoice:
    def __init__(self, delta: _FakeDelta, finish_reason: str | None = None) -> None:
        self.delta = delta
        self.finish_reason = finish_reason


class _FakeChunk:
    def __init__(self, choices: list[_FakeChoice], usage: object | None = None) -> None:
        self.choices = choices
        self.usage = usage


def _chunk(
    content: str | None = None,
    reasoning: str | None = None,
    finish_reason: str | None = None,
) -> _FakeChunk:
    """构造只含文字增量的伪 chunk(无 tool_calls)。"""
    return _FakeChunk(
        choices=[
            _FakeChoice(_FakeDelta(content=content, reasoning_content=reasoning), finish_reason)
        ]
    )


def test_stream_assembler_reasoning_concatenated_into_result() -> None:
    """reasoning_content 分片被拼接进 StepResult.reasoning。"""
    asm = StreamAssembler()
    asm.feed(_chunk(reasoning="先想想"))
    asm.feed(_chunk(reasoning="再说说"))
    asm.feed(_chunk(content="最终答案", finish_reason="stop"))
    result = asm.result()
    assert result.reasoning == "先想想再说说"
    assert result.content == "最终答案"


def test_stream_assembler_no_reasoning_gives_empty_string() -> None:
    """无任何 reasoning_content chunk → result.reasoning == ''(非思考模型向后兼容)。"""
    asm = StreamAssembler()
    asm.feed(_chunk(content="普通回答", finish_reason="stop"))
    result = asm.result()
    assert result.reasoning == ""
    assert result.content == "普通回答"


def test_stream_assembler_reasoning_emits_delta_kind_reasoning() -> None:
    """reasoning_content chunk → feed 返回 StepDelta(kind='reasoning')。"""
    asm = StreamAssembler()
    deltas = asm.feed(_chunk(reasoning="思考中"))
    assert len(deltas) == 1
    assert deltas[0].kind == "reasoning"
    assert deltas[0].text == "思考中"


def test_stream_assembler_reasoning_not_in_content_parts() -> None:
    """reasoning 不进 content_parts,content 与 reasoning 互不污染。"""
    asm = StreamAssembler()
    asm.feed(_chunk(reasoning="这是推理"))
    asm.feed(_chunk(content="这是输出", finish_reason="stop"))
    result = asm.result()
    assert result.content == "这是输出"
    assert "这是推理" not in result.content
    assert result.reasoning == "这是推理"
