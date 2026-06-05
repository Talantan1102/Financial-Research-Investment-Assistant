"""控制双工具 in-process — L0 单测(Fake cache,零 DB,spec § 3.5 / § 2.4)。

覆盖:
- offer_deep_research:置 escalate_offered / escalate_reason / tool_choice="none" + 返回 note;
- offer_deep_research:同 turn 幂等(第二次 [已提议过] ToolError);
- read_cached_result:正常切片(offset/limit)+ total_len;
- read_cached_result:越权 ref(不以 user_id:: 开头)→ [无权访问];
- read_cached_result:不存在 ref(get_raw 返回 None)→ [缓存不存在/已过期];
- read_cached_result:offset+limit 分页;
- 文档同步:TOOL_DOCS 参数与实现一致(轻断言)。
"""
from __future__ import annotations

import json

import pytest
from app.chatloop.control_tools import (
    OfferDeepResearchArgs,
    OfferDeepResearchTool,
    ReadCachedResultArgs,
    ReadCachedResultTool,
)
from app.chatloop.inprocess import InProcessTool
from app.chatloop.state import ChatLoopState
from app.chatloop.tool_docs import TOOL_DOCS
from app.chatloop.tool_hub import ToolHub
from app.services.llm_step import StepToolCall
from app.tools.base import ToolError

_USER_ID = "11111111-1111-1111-1111-111111111111"


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeCache:
    """模拟 ToolResultCache.get_raw(cache_key) -> str | None。"""

    def __init__(self, store: dict[str, str] | None = None) -> None:
        self._store = store or {}
        self.calls: list[str] = []

    async def get_raw(self, cache_key: str) -> str | None:
        self.calls.append(cache_key)
        return self._store.get(cache_key)


def _state(messages: list[dict] | None = None) -> ChatLoopState:
    s = ChatLoopState(
        user_id=_USER_ID,
        session_id="s1",
        request_id="r1",
        messages=messages or [{"role": "user", "content": "帮我做一份茅台深度尽调"}],
    )
    s.step = 1
    return s


# ===========================================================================
# offer_deep_research
# ===========================================================================


async def test_offer_deep_research_sets_three_state_fields_and_note():
    tool = OfferDeepResearchTool()
    state = _state()
    out = await tool.run_with_state(
        OfferDeepResearchArgs(reason="需跨多份研报与财报系统比对"), state
    )
    assert state.escalate_offered is True
    assert state.escalate_reason == "需跨多份研报与财报系统比对"
    # 熔断:工具调用通道关闭
    assert state.tool_choice == "none"
    assert out["escalation_proposed"] is True
    assert "note" in out
    assert "工具调用通道已关闭" in out["note"]
    json.dumps(out, ensure_ascii=False)


async def test_offer_deep_research_idempotent_second_call_rejected():
    tool = OfferDeepResearchTool()
    state = _state()
    await tool.run_with_state(OfferDeepResearchArgs(reason="第一次"), state)
    with pytest.raises(ToolError) as exc:
        await tool.run_with_state(OfferDeepResearchArgs(reason="第二次"), state)
    msg = str(exc.value)
    assert "[已提议过]" in msg
    # reason 不被第二次覆盖
    assert state.escalate_reason == "第一次"


async def test_offer_deep_research_is_inprocess_tool():
    assert isinstance(OfferDeepResearchTool(), InProcessTool)


async def test_hub_dispatch_offer_deep_research_sets_state():
    hub = ToolHub()
    hub.register_inprocess([OfferDeepResearchTool()])
    state = _state()
    call = StepToolCall(
        id="c1", name="offer_deep_research", arguments=json.dumps({"reason": "需系统调研"})
    )
    results = await hub.dispatch([call], state)
    assert results[0].success is True
    assert state.escalate_offered is True
    assert state.tool_choice == "none"


# ===========================================================================
# read_cached_result
# ===========================================================================


async def test_read_cached_result_normal_slice():
    ref = f"{_USER_ID}::get_news::abcd"
    content = "完整新闻原文" * 100
    cache = FakeCache({ref: content})
    tool = ReadCachedResultTool(cache=cache)
    out = await tool.run_with_state(ReadCachedResultArgs(ref=ref), _state())
    assert out["ref"] == ref
    assert out["offset"] == 0
    assert out["total_len"] == len(content)
    # 默认 limit 2000，content 此处 600 字，全量返回
    assert out["content"] == content[:2000]


async def test_read_cached_result_offset_limit_pagination():
    ref = f"{_USER_ID}::web_search::deadbeef"
    content = "".join(str(i % 10) for i in range(5000))
    cache = FakeCache({ref: content})
    tool = ReadCachedResultTool(cache=cache)
    out = await tool.run_with_state(
        ReadCachedResultArgs(ref=ref, offset=100, limit=50), _state()
    )
    assert out["offset"] == 100
    assert out["total_len"] == 5000
    assert out["content"] == content[100:150]
    assert len(out["content"]) == 50


async def test_read_cached_result_cross_user_ref_blocked():
    other_user = "22222222-2222-2222-2222-222222222222"
    ref = f"{other_user}::get_news::abcd"
    cache = FakeCache({ref: "敏感数据"})
    tool = ReadCachedResultTool(cache=cache)
    with pytest.raises(ToolError) as exc:
        await tool.run_with_state(ReadCachedResultArgs(ref=ref), _state())
    assert "[无权访问]" in str(exc.value)
    # 越权校验先于 cache 读取(不泄露存在性)
    assert cache.calls == []


async def test_read_cached_result_missing_ref():
    ref = f"{_USER_ID}::get_news::notexist"
    cache = FakeCache({})  # 空
    tool = ReadCachedResultTool(cache=cache)
    with pytest.raises(ToolError) as exc:
        await tool.run_with_state(ReadCachedResultArgs(ref=ref), _state())
    msg = str(exc.value)
    assert "[缓存不存在/已过期]" in msg
    assert cache.calls == [ref]  # 确实查了 cache


async def test_read_cached_result_is_inprocess_tool():
    assert isinstance(ReadCachedResultTool(cache=FakeCache()), InProcessTool)


async def test_hub_dispatch_read_cached_result():
    ref = f"{_USER_ID}::get_news::abcd"
    cache = FakeCache({ref: "原文 ABC"})
    hub = ToolHub()
    hub.register_inprocess([ReadCachedResultTool(cache=cache)])
    state = _state()
    call = StepToolCall(
        id="c1", name="read_cached_result", arguments=json.dumps({"ref": ref})
    )
    results = await hub.dispatch([call], state)
    assert results[0].success is True
    assert results[0].output["content"] == "原文 ABC"


# ===========================================================================
# 文档同步
# ===========================================================================


def test_docs_offer_deep_research_params_match_impl():
    fields = set(OfferDeepResearchArgs.model_fields.keys())
    assert fields == {"reason"}
    doc = TOOL_DOCS["offer_deep_research"].doc
    assert "reason" in doc


def test_docs_read_cached_result_params_match_impl():
    fields = set(ReadCachedResultArgs.model_fields.keys())
    assert fields == {"ref", "offset", "limit"}
    doc = TOOL_DOCS["read_cached_result"].doc
    assert "ref" in doc
    assert "offset" in doc
    assert "limit" in doc


def test_tool_names_match_docs():
    assert OfferDeepResearchTool().name == "offer_deep_research"
    assert ReadCachedResultTool(cache=FakeCache()).name == "read_cached_result"
