"""L2 cassette — chatloop 主路径,真 DashScope LLM 录制 / VCR 回放(Task 6.3)。

裸 while 重设计后的 SUT 是 ``ChatLoopAgent``(app.chatloop.eval_agent),不是退役的
老 ChatAgent(test_chat_agent_cassette 那条 SKIPPED,Phase 7 删)。本测试录三条主路径:

1. 单工具直答 —— "贵州茅台现在股价多少?" → 模型调 get_stock_quote → 终答含价格;
2. 多跳 —— "对比贵州茅台和五粮液的最新毛利率" → 财务三表两次 / compare_stocks 都可;
3. 升级 —— "帮我全面深入研究下宁德时代值不值得投…" → offer_deep_research 置 state → 熔断收尾。

关键设计(吸取 test_chat_agent_cassette 被 tushare 副流量搞挂的教训):
    **磁带只锁 LLM 行为,工具结果本地确定性给。** 14 个业务工具用 FakeTool 注册
    (dispatch 返回预设 dict,不打真 tushare/MCP),所以磁带里只有 LLM 的 HTTP 流量,
    工具执行零副流量。唯一例外是 offer_deep_research —— 用真 OfferDeepResearchTool
    (它要置 state.escalate_offered / tool_choice=none,Fake 替身会丢掉这层语义)。

工具表与生产一致:FakeTool 按 TOOL_DOCS 的 14 个真实工具名注册,``ToolHub.schemas_for_llm``
    对 core/deferred 两组用 TOOL_DOCS / thin_schema 产 schema(不取工具自身 schema),
    core 组的参数则取工具 schema_for_llm —— 故数据工具用与 _MCPToolProxy 同款的宽松
    ``extra=allow`` args_schema,产出的工具表逐字等同生产(MCP 路径)。

流式 VCR:stream_step 走 AsyncOpenAI streaming(httpx chunked body),vcrpy 8.x 能录
    回放(同 test_path_b_cross_turn_cassette 已验证的 build_llm_service_from_env 流式路径)。

录制:
    wsl ... VCR_RECORD_MODE=once python -m pytest \
        backend/tests/e2e/test_chatloop_cassette.py -q
回放(离线,默认):
    wsl ... python -m pytest backend/tests/e2e/test_chatloop_cassette.py -q
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from app.chatloop.context import ContextDeps
from app.chatloop.control_tools import OfferDeepResearchTool
from app.chatloop.eval_agent import ChatLoopAgent
from app.chatloop.gates import GateConfig
from app.chatloop.system_prompt import CHAT_SYSTEM_PROMPT
from app.chatloop.tool_docs import CORE_TOOLS, DEFERRED_TOOLS
from app.chatloop.tool_hub import ToolHub
from app.services.openai_client import build_llm_service_from_env
from app.tools.base import Tool
from pydantic import BaseModel, ConfigDict

pytestmark = [pytest.mark.e2e]

CASSETTE_DIR = Path(__file__).resolve().parent / "fixtures" / "cassettes" / "test_chatloop_cassette"
# 注:vcr_cassette_dir 全局 fixture 把磁带落到 backend/tests/fixtures/cassettes/<module>/
# (sanitize pre-commit hook 只覆盖该目录)。上方常量仅供 _skip_if_no_cassette 判存在。
_FIXTURES_CASSETTE_DIR = (
    Path(__file__).resolve().parent.parent / "fixtures" / "cassettes" / "test_chatloop_cassette"
)


# ---------------------------------------------------------------------------
# FakeTool —— dispatch 层确定性替身(工具不打真 API,只让 LLM 流量上磁带)
# ---------------------------------------------------------------------------


class _PermissiveArgs(BaseModel):
    """与 ToolRegistry._MCPToolProxy._Args 同款:宽松 extra=allow。

    生产里数据工具经 MCP 走 _MCPToolProxy,其 args_schema 就是这个宽松模型;
    core 组 schema 的参数取自 tool.schema_for_llm() → 用同款模型保证工具表逐字一致。
    """

    model_config = ConfigDict(extra="allow")


class _FakeTool(Tool):
    """按真实工具名注册的 dispatch 替身,run 返回预设结果(不打真 API)。

    description 在 core/deferred 两组里会被 ToolHub 用 TOOL_DOCS.brief / thin_schema
    覆盖(不取本字段),仅 fail-safe 分支才会用到 —— 14 个名字都在 TOOL_DOCS 里,
    故本 description 实际不进工具表,占位即可。
    """

    def __init__(self, name: str, result: dict[str, Any]) -> None:
        self.name = name
        self.description = f"{name}(fake dispatch — 测试替身)"
        self.args_schema = _PermissiveArgs
        self._result = result

    async def run(self, args: BaseModel) -> dict[str, Any]:  # noqa: ARG002
        return self._result


# 预设工具结果(确定性,断言锚点在这里:茅台 1700.0 / 五粮液毛利率)
_FAKE_RESULTS: dict[str, dict[str, Any]] = {
    "get_stock_quote": {
        "ts_code": "600519.SH",
        "name": "贵州茅台",
        "close": 1700.0,
        "pct_chg": 1.23,
        "trade_date": "20260604",
        "unit": "元",
    },
    "get_financial_statements": {
        # 多跳路径:模型对两家各调一次,Fake 用通用毛利率快照(args 区分由模型自管)
        "ts_code": "600519.SH",
        "statement": "income",
        "gross_margin": 0.915,
        "revenue": 150_000_000_000,
        "net_profit": 74_000_000_000,
        "roe": 0.31,
        "report_period": "20260331",
    },
    "compare_stocks": {
        "compared": [
            {"ts_code": "600519.SH", "name": "贵州茅台", "gross_margin": 0.915},
            {"ts_code": "000858.SZ", "name": "五粮液", "gross_margin": 0.758},
        ]
    },
    "kb_search": {"hits": [{"title": "占位研报", "snippet": "占位内容", "score": 0.5}]},
    "memory_search": {"results": []},
    "load_skill": {"loaded": False, "note": "fake"},
    "get_market_indicators": {"ts_code": "600519.SH", "pe": 30.0, "pb": 9.0},
    "get_corporate_actions": {"ts_code": "600519.SH", "actions": []},
    "get_news": {"items": []},
    "web_search": {"results": []},
    "memory_write": {"ok": True},
    "run_skill_script": {"stdout": "", "stderr": "", "return_code": 0},
    "read_cached_result": {"content": "", "total_len": 0, "offset": 0},
    # run_python(#143)/dispatch_subagents(#144)/get_daily+get_portfolio_positions
    # (charting)进 CORE/DEFERRED 后,harness 按 CORE+DEFERRED 全量造 fake;这 3 条主路径
    # cassette 录于它们之前、不会调它们(VCR 按 path 匹配,不受新增工具 schema 影响),
    # fake 占位即可、永不被调用。
    "run_python": {"result": {}, "figures": []},
    "dispatch_subagents": {"dispatched": 0, "results": []},
    "get_daily": {"ts_code": "600519.SH", "count": 0, "dates": [], "close": []},
    "get_portfolio_positions": {"total_count": 0, "positions": [], "total_market_value": 0.0},
    "get_index_daily": {"ts_code": "000300.SH", "count": 0, "latest": None},
    "get_fund_nav": {"ts_code": "110011.OF", "fund_type": None, "latest": None},
}


def _build_chatloop_agent() -> ChatLoopAgent:
    """构造录制/回放用 ChatLoopAgent:真 LLMService(流式)+ Fake 工具表 + 真升级工具。

    - LLMService:build_llm_service_from_env(真 AsyncOpenAI,HTTP 经 vcr 录/放;
      trace_service 不接 DB —— 显式传 None,span 写入静默跳过,不碰 PG);
    - ToolHub:13 个数据/记忆/技能/取回 FakeTool(按 TOOL_DOCS 名注册)+ 真
      OfferDeepResearchTool(升级语义须真执行);offer_deep_research 不给 Fake;
    - ContextDeps:真 CHAT_SYSTEM_PROMPT,persona/skill_listing/history 全空。
    """
    # _NullTrace 是只实现 write_span 的轻量测试替身;TraceService 是具体类(非
    # Protocol),mypy 不认结构化等价,但运行时只调 write_span,故安全。
    llm = build_llm_service_from_env(trace_service=_NullTrace())  # type: ignore[arg-type]

    hub = ToolHub()  # 无 emit / 无 cache(InProcessTool 不吃 cache;数据工具 Fake 不需缓存)
    fake_names = [n for n in (*CORE_TOOLS, *DEFERRED_TOOLS) if n != "offer_deep_research"]
    hub.register_inprocess([_FakeTool(name, _FAKE_RESULTS[name]) for name in fake_names])
    # 升级路径用真控制工具(置 state.escalate_offered / tool_choice=none)
    hub.register_inprocess([OfferDeepResearchTool()])

    context_deps = ContextDeps(
        system_prompt=CHAT_SYSTEM_PROMPT,
        persona_block="",
        skill_listing="",
        history_block=(),
        max_steps=GateConfig().max_steps,
        max_cny=GateConfig().max_cny,
    )

    return ChatLoopAgent(
        llm=llm,
        tool_hub=hub,
        context_deps=context_deps,
        gate_cfg=GateConfig(),
    )


class _NullTrace:
    """trace_service 替身 —— write_span no-op,不接 DB(构造轻量,不碰 PG)。"""

    def write_span(self, span: Any) -> None:  # noqa: ARG002
        return None


def _skip_if_no_cassette(test_name: str) -> None:
    """回放模式下磁带缺失则 skip(fresh checkout / 无 secret 时 CI 仍绿)。"""
    record_mode = os.environ.get("VCR_RECORD_MODE", "none")
    cassette = _FIXTURES_CASSETTE_DIR / f"{test_name}.yaml"
    if record_mode == "none" and not cassette.exists():
        pytest.skip(
            f"cassette {cassette.name} 未录制;先 VCR_RECORD_MODE=once + DASHSCOPE_API_KEY 录制"
        )


# ---------------------------------------------------------------------------
# VCR config —— 不匹配 body(流式 prompt 含动态步号/预算,按串行录制顺序回放)
# ---------------------------------------------------------------------------


def _strip_dashscope_response_headers(response: dict[str, Any]) -> dict[str, Any]:
    headers = response.get("headers", {})
    response["headers"] = {k: v for k, v in headers.items() if "dashscope" not in k.lower()}
    return response


@pytest.fixture(scope="module")
def vcr_config() -> dict[str, Any]:
    """覆盖全局 vcr_config:剔除 body 匹配。

    尾部动态区每圈带「第 N/M 步,预算剩 ¥x.xx」,录制与回放时步号/预算字面不同;
    多圈对话的 messages 也随轨迹增长。故只按 method+scheme+host+port+path 串行顺序
    匹配(对单靶单端点的多请求确定性,沿用既有 cassette 基建口径)。
    """
    return {
        "filter_headers": [
            "authorization",
            "x-dashscope-api-key",
            "x-api-key",
            "openai-organization",
        ],
        "filter_post_data_parameters": [],
        "decode_compressed_response": True,
        "record_mode": os.environ.get("VCR_RECORD_MODE", "none"),
        "match_on": ["method", "scheme", "host", "port", "path"],
        "before_record_response": _strip_dashscope_response_headers,
    }


# ---------------------------------------------------------------------------
# 三条主路径
# ---------------------------------------------------------------------------


@pytest.mark.vcr
@pytest.mark.asyncio
async def test_chatloop_single_tool() -> None:
    """单工具直答:模型调 get_stock_quote(Fake 1700.0)→ 终答含价格。"""
    _skip_if_no_cassette("test_chatloop_single_tool")
    agent = _build_chatloop_agent()
    out = await agent.run("贵州茅台现在股价多少?", request_id="cassette-single-tool")

    tool_names = [tc.tool_name for tc in out.tool_calls]
    assert "get_stock_quote" in tool_names, f"期望调 get_stock_quote,实得 {tool_names!r}"
    assert out.response_text, "final_response 不应为空"
    # 去千分位逗号再判:模型常把 1700 格式化成 "1,700.00"(行为非确定性,锚价格数字本身)
    assert "1700" in out.response_text.replace(",", "").replace("，", ""), (
        f"终答应含 Fake 行情价 1700:{out.response_text!r}"
    )


@pytest.mark.vcr
@pytest.mark.asyncio
async def test_chatloop_multi_hop() -> None:
    """多跳:对比茅台/五粮液毛利率 → 财务工具或 compare,终答含两家名字。"""
    _skip_if_no_cassette("test_chatloop_multi_hop")
    agent = _build_chatloop_agent()
    out = await agent.run("对比贵州茅台和五粮液的最新毛利率", request_id="cassette-multi-hop")

    tool_names = [tc.tool_name for tc in out.tool_calls]
    assert tool_names, f"多跳应至少调一个业务工具,实得空:{tool_names!r}"
    assert any("financial" in n or "compare" in n for n in tool_names), (
        f"期望 financial / compare 类工具,实得 {tool_names!r}"
    )
    assert out.response_text, "final_response 不应为空"
    assert "茅台" in out.response_text and "五粮液" in out.response_text, (
        f"终答应同时含两家名字:{out.response_text!r}"
    )


@pytest.mark.vcr
@pytest.mark.asyncio
async def test_chatloop_escalation() -> None:
    """升级:深研诉求 → offer_deep_research 置 state → 熔断收尾,escalate_offered=True。"""
    _skip_if_no_cassette("test_chatloop_escalation")
    agent = _build_chatloop_agent()
    # 直接请求「启动深度研究专门流程」—— 显式对齐 offer_deep_research 作为升级信号工具的
    # 语义。前两次「做一份深度尽调」措辞模型仍当快问快答自己拉数据(见报告重录记录),
    # 故第 3 次直说要那个独立深研子流程,触发模型提议升级而非自答。
    out = await agent.run(
        "宁德时代值不值得投这个问题太大,普通对话答不充分。请帮我启动你那个"
        "「深度研究」专门子流程来系统做这件事(多源调研 + 多模型估值交叉验证 + 成稿),"
        "在普通对话里简单查数据是不够的。",
        request_id="cassette-escalation",
    )

    assert out.escalate_offered is True, "应触发 offer_deep_research 置 escalate_offered"
    assert out.response_text, "熔断收尾后 final_response 不应为空"
