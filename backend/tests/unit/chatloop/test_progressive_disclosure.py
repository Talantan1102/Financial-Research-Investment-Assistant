"""工具渐进披露 — L0 单测(tool_docs 内容层 + tool_hub 分组叠加,spec § 3.2)。

覆盖:
- thin_schema:必填参数名+类型保留、description=brief、无 enum/示例/可选参数;
- schemas_for_llm:core 全 schema / deferred 瘦 / search_tools 殿后 / core 在前 / 未知工具 fail-safe;
- search_docs:关键词评分检索(中文 2-gram + 工具名直查 + k 截断);
- search_tools dispatch:返回 docs、searched_docs 记账、重复检索带标记;
- 裸调指导:deferred 工具 ValidationError 错误文案含 search_tools 提示;
- 文档完整性守卫:15 个全有非空 brief/doc、CORE+DEFERRED 并集=15 无重叠、金融 8 含"何时不用"。
"""

from __future__ import annotations

import asyncio
import json

from app.chatloop.events import LoopEvent
from app.chatloop.state import ChatLoopState
from app.chatloop.tool_docs import (
    CORE_TOOLS,
    DEFERRED_TOOLS,
    TOOL_DOCS,
    ToolDoc,
    search_docs,
    thin_schema,
)
from app.chatloop.tool_hub import ToolHub
from app.services.llm_step import StepToolCall
from app.tools.base import Tool
from pydantic import BaseModel

# asyncio_mode=auto(pyproject)自动识别 async 测试,无需 pytestmark;
# 本文件混 sync + async 测试,不加模块级 asyncio 标记(否则 sync 测试告警)。


# ---------------------------------------------------------------------------
# Fakes —— 名字对上 TOOL_DOCS 的假工具
# ---------------------------------------------------------------------------

# 金融工具的真实必填字段(与 mcp_server TOOL_DEF 一致)
_REQUIRED: dict[str, dict[str, type]] = {
    "get_stock_quote": {"ts_code": str},
    "get_financial_statements": {"ts_code": str, "statement": str},
    "get_market_indicators": {"ts_code": str, "metric": str},
    "get_corporate_actions": {"ts_code": str, "action": str},
    "get_news": {},
    "web_search": {"query": str},
    "kb_search": {"query": str},
    "compare_stocks": {"ts_codes": list},
}


def _args_model(name: str) -> type[BaseModel]:
    """按真实必填字段造一个最小 pydantic 模型(校验路径用)。"""
    fields: dict[str, object] = {}
    for fname, ftype in _REQUIRED.get(name, {}).items():
        fields[fname] = (ftype, ...)
    # in-process 工具默认无必填(用空模型)
    from pydantic import create_model

    return create_model(f"_{name}_Args", **fields)  # type: ignore[call-overload]


class FakeTool(Tool):
    def __init__(self, name: str, *, output: dict | None = None) -> None:
        self.name = name
        self.description = f"real schema for {name}"
        self.args_schema = _args_model(name)
        self._output = output if output is not None else {"ok": True}

    async def run(self, args: BaseModel) -> dict:
        return dict(self._output)


class _Collector:
    def __init__(self) -> None:
        self.events: list[LoopEvent] = []

    async def __call__(self, ev: LoopEvent) -> None:
        self.events.append(ev)


def _all_fake_tools() -> list[FakeTool]:
    return [FakeTool(name) for name in TOOL_DOCS]


def _state() -> ChatLoopState:
    s = ChatLoopState(
        user_id="u1",
        session_id="s1",
        request_id="r1",
        messages=[{"role": "user", "content": "茅台"}],
    )
    s.step = 1
    return s


def _call(name: str, args: dict) -> StepToolCall:
    return StepToolCall(id=f"{name}-1", name=name, arguments=json.dumps(args, ensure_ascii=False))


# ---------------------------------------------------------------------------
# 文档完整性守卫
# ---------------------------------------------------------------------------


def test_tool_docs_count_is_16():
    # 16 = 原 15 + dispatch_subagents(2026-06-11 chat 内子 agent 派发,进延迟组)
    assert len(TOOL_DOCS) == 16


def test_core_and_deferred_partition_no_overlap():
    core = set(CORE_TOOLS)
    deferred = set(DEFERRED_TOOLS)
    assert len(CORE_TOOLS) == 7
    assert len(DEFERRED_TOOLS) == 9  # +dispatch_subagents
    assert core & deferred == set()
    assert core | deferred == set(TOOL_DOCS.keys())


def test_every_doc_has_nonempty_brief_and_doc():
    for name, doc in TOOL_DOCS.items():
        assert doc.brief.strip(), f"{name} brief 为空"
        assert doc.doc.strip(), f"{name} doc 为空"
        assert doc.name == name, f"{name} doc.name 不一致"
        assert doc.group in ("core", "deferred")


def test_brief_within_80_chars():
    for name, doc in TOOL_DOCS.items():
        assert len(doc.brief) <= 80, f"{name} brief 超 80 字: {len(doc.brief)}"


def test_financial_eight_have_when_not_to_use():
    financial = [
        "get_stock_quote",
        "get_financial_statements",
        "get_market_indicators",
        "get_corporate_actions",
        "get_news",
        "web_search",
        "kb_search",
        "compare_stocks",
    ]
    for name in financial:
        assert name in TOOL_DOCS, f"{name} 不在 TOOL_DOCS"
        assert "何时不用" in TOOL_DOCS[name].doc, f"{name} 文档缺'何时不用'"


def test_deferred_docs_have_thin_required_core_have_none():
    for name in CORE_TOOLS:
        assert TOOL_DOCS[name].group == "core"
    for name in DEFERRED_TOOLS:
        assert TOOL_DOCS[name].group == "deferred"
        # thin_required 不为 None(可为空 dict,如 get_news 无必填)
        assert TOOL_DOCS[name].thin_required is not None, f"{name} 缺 thin_required"


def test_deferred_thin_required_matches_real_required():
    """瘦 schema 必填字段必须与真实 TOOL_DEF 必填一致。"""
    for name in DEFERRED_TOOLS:
        doc = TOOL_DOCS[name]
        if name in _REQUIRED:
            expected = set(_REQUIRED[name].keys())
            assert set(doc.thin_required or {}) == expected, (
                f"{name} thin_required {set(doc.thin_required or {})} != 真实必填 {expected}"
            )


# ---------------------------------------------------------------------------
# thin_schema
# ---------------------------------------------------------------------------


def test_thin_schema_keeps_required_name_and_type():
    doc = TOOL_DOCS["compare_stocks"]
    schema = thin_schema(doc)
    fn = schema["function"]
    assert schema["type"] == "function"
    assert fn["name"] == "compare_stocks"
    props = fn["parameters"]["properties"]
    assert "ts_codes" in props
    assert props["ts_codes"]["type"] == "array"
    assert fn["parameters"]["required"] == ["ts_codes"]


def test_thin_schema_description_is_brief():
    doc = TOOL_DOCS["compare_stocks"]
    schema = thin_schema(doc)
    assert schema["function"]["description"] == doc.brief


def test_thin_schema_strips_enum_and_examples():
    """瘦条目剥掉 enum/示例/可选参数 —— 只留必填名+类型。"""
    doc = TOOL_DOCS["get_market_indicators"]  # 真实有 enum 的 metric
    schema = thin_schema(doc)
    serialized = json.dumps(schema, ensure_ascii=False)
    assert "enum" not in serialized, "瘦 schema 不应含 enum"
    props = schema["function"]["parameters"]["properties"]
    # 只保留必填(ts_code + metric),剥掉可选(trade_date/years_back/...)
    assert set(props.keys()) == {"ts_code", "metric"}
    # 必填参数无 description(细节走文档)
    for p in props.values():
        assert "description" not in p


def test_thin_schema_no_required_tool_has_empty_properties():
    """get_news 无必填 —— 但仍是可调瘦 schema(非空 properties 不强求,required 空)。"""
    doc = TOOL_DOCS["get_news"]
    schema = thin_schema(doc)
    fn = schema["function"]
    assert fn["parameters"].get("required", []) == []
    assert fn["description"] == doc.brief


# ---------------------------------------------------------------------------
# search_docs
# ---------------------------------------------------------------------------


def test_search_docs_compare_in_top3():
    # 对比类查询应召回对比能力工具。2026-06-11 起 dispatch_subagents(多标的并发扇出)
    # 与 compare_stocks(2-5 只内联对比)同为对比工具,二者命中其一即满足召回意图。
    results = search_docs("对比 茅台 五粮液", k=3)
    names = [d.name for d in results]
    assert {"compare_stocks", "dispatch_subagents"} & set(names), (
        f"对比类查询未召回任何对比工具: {names}"
    )


def test_search_docs_memory_preference():
    results = search_docs("用户偏好 持仓 历史观点", k=3)
    names = [d.name for d in results]
    assert "memory_search" in names


def test_search_docs_tool_name_direct_hit_first():
    results = search_docs("compare_stocks", k=3)
    assert results
    assert results[0].name == "compare_stocks"


def test_search_docs_k_truncates():
    results = search_docs("茅台 财报 估值 资金 新闻 对比 记忆 技能", k=2)
    assert len(results) <= 2


def test_search_docs_returns_tooldoc_instances():
    results = search_docs("compare_stocks", k=1)
    assert all(isinstance(d, ToolDoc) for d in results)


# ---------------------------------------------------------------------------
# schemas_for_llm 分组叠加
# ---------------------------------------------------------------------------


async def test_schemas_for_llm_groups_core_full_deferred_thin_search_last():
    hub = ToolHub()
    hub.register_inprocess(_all_fake_tools())
    schemas = hub.schemas_for_llm()
    names = [s["function"]["name"] for s in schemas]

    # 总数 = 16 + search_tools = 17(+dispatch_subagents)
    assert len(names) == 17
    # search_tools 殿后
    assert names[-1] == "search_tools"
    # core 6 在前(顺序 = CORE_TOOLS)
    assert names[: len(CORE_TOOLS)] == CORE_TOOLS
    # 紧接 deferred 9(顺序 = DEFERRED_TOOLS)
    assert names[len(CORE_TOOLS) : len(CORE_TOOLS) + len(DEFERRED_TOOLS)] == DEFERRED_TOOLS


async def test_schemas_for_llm_core_keeps_full_params():
    hub = ToolHub()
    hub.register_inprocess(_all_fake_tools())
    schemas = {s["function"]["name"]: s for s in hub.schemas_for_llm()}
    # get_financial_statements 是 core —— 完整参数(含可选 end_date/period 由真实 schema 决定)
    fin = schemas["get_financial_statements"]
    props = fin["function"]["parameters"]["properties"]
    # core 用真实工具 schema 参数:ts_code + statement 必填
    assert "ts_code" in props
    assert "statement" in props


async def test_schemas_for_llm_deferred_is_thin():
    hub = ToolHub()
    hub.register_inprocess(_all_fake_tools())
    schemas = {s["function"]["name"]: s for s in hub.schemas_for_llm()}
    mkt = schemas["get_market_indicators"]  # deferred
    serialized = json.dumps(mkt, ensure_ascii=False)
    assert "enum" not in serialized
    props = mkt["function"]["parameters"]["properties"]
    assert set(props.keys()) == {"ts_code", "metric"}
    assert mkt["function"]["description"] == TOOL_DOCS["get_market_indicators"].brief


async def test_schemas_for_llm_unknown_tool_full_schema_no_crash(caplog):
    """未在 TOOL_DOCS 的注册工具 → 完整 schema + warning,不炸。"""
    import logging

    hub = ToolHub()
    hub.register_inprocess([FakeTool("brand_new_tool")])
    with caplog.at_level(logging.WARNING):
        schemas = hub.schemas_for_llm()
    names = [s["function"]["name"] for s in schemas]
    assert "brand_new_tool" in names
    # 未知工具用完整 schema(description 是工具自身的,非 brief)
    new = next(s for s in schemas if s["function"]["name"] == "brand_new_tool")
    assert new["function"]["description"] == "real schema for brand_new_tool"
    # fail-safe warning
    assert any("brand_new_tool" in rec.message for rec in caplog.records)
    # search_tools 仍殿后
    assert names[-1] == "search_tools"


async def test_search_tools_schema_query_required():
    hub = ToolHub()
    hub.register_inprocess([FakeTool("get_stock_quote")])
    schemas = {s["function"]["name"]: s for s in hub.schemas_for_llm()}
    st = schemas["search_tools"]
    params = st["function"]["parameters"]
    assert params["properties"]["query"]["type"] == "string"
    assert params["required"] == ["query"]


# ---------------------------------------------------------------------------
# search_tools dispatch
# ---------------------------------------------------------------------------


async def test_dispatch_search_tools_returns_docs_and_records():
    emit = _Collector()
    hub = ToolHub(emit=emit)
    hub.register_inprocess(_all_fake_tools())
    state = _state()
    results = await hub.dispatch([_call("search_tools", {"query": "compare_stocks"})], state)
    r = results[0]
    assert r.success is True
    assert "docs" in r.output
    docs = r.output["docs"]
    assert docs
    assert all("name" in d and "doc" in d for d in docs)
    # searched_docs 记账(命中工具名进集合)
    assert "compare_stocks" in state.ledger.searched_docs
    # 也走 tool_call/tool_start/tool_end 事件序列(不走 tool_error)
    types = [e.type for e in emit.events]
    assert types == ["tool_call", "tool_start", "tool_end"]
    # 台账也记一条 search_tools success
    assert state.ledger.entries[-1].tool_name == "search_tools"
    assert state.ledger.entries[-1].success is True


async def test_dispatch_search_tools_repeat_marks_already_searched():
    hub = ToolHub()
    hub.register_inprocess(_all_fake_tools())
    state = _state()
    await hub.dispatch([_call("search_tools", {"query": "compare_stocks"})], state)
    second = await hub.dispatch([_call("search_tools", {"query": "compare_stocks"})], state)
    docs = second[0].output["docs"]
    # 第二次同一工具文档前加标记
    target = next(d for d in docs if d["name"] == "compare_stocks")
    assert "本 turn 已检索过" in target["doc"]


async def test_dispatch_search_tools_not_a_registered_tool_instance():
    """search_tools 内置,不需注册 Tool 实例也能 dispatch。"""
    hub = ToolHub()
    hub.register_inprocess([FakeTool("get_stock_quote")])  # 不含 search_tools 实例
    state = _state()
    results = await hub.dispatch([_call("search_tools", {"query": "茅台 行情"})], state)
    assert results[0].success is True
    assert "docs" in results[0].output


# ---------------------------------------------------------------------------
# 裸调 deferred 工具参数错 → 指导含 search_tools
# ---------------------------------------------------------------------------


async def test_bare_call_deferred_validation_error_suggests_search_tools():
    hub = ToolHub()
    hub.register_inprocess(_all_fake_tools())
    state = _state()
    # get_market_indicators 缺必填 metric → ValidationError
    results = await hub.dispatch([_call("get_market_indicators", {"ts_code": "600519.SH"})], state)
    r = results[0]
    assert r.success is False
    assert "[参数校验失败]" in r.error
    assert "search_tools" in r.error
    assert "get_market_indicators" in r.error


# ---------------------------------------------------------------------------
# 无回归:基线 schema 行为(无 TOOL_DOCS 命中的纯 in-process 仍可用)
# ---------------------------------------------------------------------------


async def test_parallel_search_and_normal_call():
    hub = ToolHub()
    hub.register_inprocess(_all_fake_tools())
    state = _state()
    results = await asyncio.gather(
        hub.dispatch([_call("get_stock_quote", {"ts_code": "600519.SH"})], state),
        hub.dispatch([_call("search_tools", {"query": "财报"})], state),
    )
    assert results[0][0].success is True
    assert results[1][0].success is True
