"""非 deepseek 模型兼容垫片:qwen3 关思考 + tool_call args 合法化(承 2026-06-18 排查)。"""

from app.services.openai_client import _extra_body_for, _sanitize_tool_args


def test_extra_body_qwen3_disables_thinking() -> None:
    assert _extra_body_for("qwen3-8b") == {"enable_thinking": False}
    assert _extra_body_for("qwen3-32b") == {"enable_thinking": False}
    assert _extra_body_for("deepseek-v4-flash") == {}
    assert _extra_body_for("qwen-max") == {}


def test_sanitize_empty_and_invalid_args_to_empty_object() -> None:
    msgs = [
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
