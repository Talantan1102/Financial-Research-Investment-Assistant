"""Smoke test: qwen/DashScope compatible-mode native function calling 能力实测.

跑法(WSL): python backend/scripts/smoke_native_tools.py
按 spec § 2.1 清单逐项验证,结果打印为 markdown 表格行。
"""

from __future__ import annotations

import json
import os

from openai import OpenAI

MODEL = os.getenv("SMOKE_MODEL", "deepseek-v4-flash")
client = OpenAI(
    api_key=os.environ["DASHSCOPE_API_KEY"],
    base_url=os.environ.get("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_stock_quote",
            "description": "查询单只 A 股实时行情。何时用:问现价/涨跌幅。ts_code 须带后缀如 600519.SH",
            "parameters": {
                "type": "object",
                "properties": {"ts_code": {"type": "string"}},
                "required": ["ts_code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_news",
            "description": "查询个股最新新闻。",
            "parameters": {
                "type": "object",
                "properties": {"ts_code": {"type": "string"}},
                "required": ["ts_code"],
            },
        },
    },
]
THIN_TOOL = [
    {  # 瘦 schema:开放参数声明(item 8)
        "type": "function",
        "function": {
            "name": "compare_stocks",
            "description": "对比多只股票。需先检索文档获取参数细节。",
            "parameters": {"type": "object", "properties": {}},
        },
    }
]
MSG = [{"role": "user", "content": "贵州茅台现在股价多少?"}]
MSG_PARALLEL = [{"role": "user", "content": "同时查贵州茅台的股价和最新新闻"}]


def check(name: str, fn) -> None:
    try:
        ok, detail = fn()
        print(f"| {name} | {'PASS' if ok else 'FAIL'} | {detail} |")
    except Exception as e:  # noqa: BLE001
        print(f"| {name} | ERROR | {type(e).__name__}: {str(e)[:120]} |")


def t1_native_tool_call():
    r = client.chat.completions.create(model=MODEL, messages=MSG, tools=TOOLS)
    c = r.choices[0]
    return (
        c.finish_reason == "tool_calls" and bool(c.message.tool_calls),
        f"finish_reason={c.finish_reason}, calls={[t.function.name for t in (c.message.tool_calls or [])]}",
    )


def t2_stream_delta_shape():
    s = client.chat.completions.create(model=MODEL, messages=MSG, tools=TOOLS, stream=True)
    frags: dict[int, dict] = {}
    finish = None
    for chunk in s:
        ch = chunk.choices[0] if chunk.choices else None
        if ch is None:
            continue
        finish = ch.finish_reason or finish
        for tc in ch.delta.tool_calls or []:
            f = frags.setdefault(tc.index, {"id": None, "name": None, "args": ""})
            if tc.id:
                f["id"] = tc.id
            if tc.function and tc.function.name:
                f["name"] = tc.function.name
            if tc.function and tc.function.arguments:
                f["args"] += tc.function.arguments
    parsed = {i: json.loads(f["args"]) for i, f in frags.items() if f["args"]}
    return (
        bool(frags) and all(f["name"] for f in frags.values()) and bool(parsed),
        f"finish={finish}, assembled={ {i: (f['name'], parsed.get(i)) for i, f in frags.items()} }",
    )


def t3_parallel_calls():
    r = client.chat.completions.create(model=MODEL, messages=MSG_PARALLEL, tools=TOOLS)
    calls = r.choices[0].message.tool_calls or []
    return (len(calls) >= 2, f"n_calls={len(calls)}: {[t.function.name for t in calls]}")


def t4_thinking_roundtrip():
    # qwen thinking 形态探测:看响应里是否有 reasoning_content;有则记录,无则 N/A
    r = client.chat.completions.create(
        model=MODEL, messages=MSG, tools=TOOLS, extra_body={"enable_thinking": True}
    )
    msg = r.choices[0].message
    rc = getattr(msg, "reasoning_content", None)
    return (
        True,
        f"reasoning_content={'present' if rc else 'absent'}(absent=不做 reasoning 折叠区,非失败)",
    )


def t5_stream_usage():
    s = client.chat.completions.create(
        model=MODEL, messages=MSG, tools=TOOLS, stream=True, stream_options={"include_usage": True}
    )
    usage = None
    for chunk in s:
        if chunk.usage:
            usage = chunk.usage
    return (usage is not None, f"prompt={getattr(usage, 'prompt_tokens', None)}")


def t6_cache_hit():
    big_sys = [
        {"role": "system", "content": "你是金融研究助手。" + "工具使用纪律细则。" * 200}
    ] + MSG
    client.chat.completions.create(model=MODEL, messages=big_sys, tools=TOOLS)
    r2 = client.chat.completions.create(model=MODEL, messages=big_sys, tools=TOOLS)
    d = getattr(r2.usage, "prompt_tokens_details", None)
    cached = getattr(d, "cached_tokens", None) if d else None
    return (bool(cached), f"cached_tokens={cached}(0/None=隐式缓存未命中,记录但非阻塞)")


def t7_tool_choice_none():
    r = client.chat.completions.create(model=MODEL, messages=MSG, tools=TOOLS, tool_choice="none")
    c = r.choices[0]
    return (
        not c.message.tool_calls and bool(c.message.content),
        f"finish={c.finish_reason}, content_len={len(c.message.content or '')}",
    )


def t8_thin_schema():
    r = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": "对比茅台和五粮液"}],
        tools=TOOLS + THIN_TOOL,
    )
    calls = r.choices[0].message.tool_calls or []
    return (True, f"calls={[t.function.name for t in calls]}(观察模型对瘦 schema 工具的调用行为)")


print(f"## Smoke results — model={MODEL}\n\n| item | result | detail |\n|---|---|---|")
for n, f in [
    ("1 native tool_calls", t1_native_tool_call),
    ("2 stream delta 拼接", t2_stream_delta_shape),
    ("3 parallel calls", t3_parallel_calls),
    ("4 thinking 形态", t4_thinking_roundtrip),
    ("5 stream usage", t5_stream_usage),
    ("6 隐式缓存命中", t6_cache_hit),
    ("7 tool_choice=none", t7_tool_choice_none),
    ("8 瘦 schema 行为", t8_thin_schema),
]:
    check(n, f)
