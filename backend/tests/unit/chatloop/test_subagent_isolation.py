"""L0 — 隔离铁律守卫:子循环只读、禁串门(无 offer_deep_research)、禁递归。

对应 spec 2026-06-11 §三隔离铁律。子循环复用 chat 的 ToolLoop,但只读白名单
不含写/升级/递归工具,从权限上堵死"chat 子循环漏进深度研报世界"。
"""

from __future__ import annotations

from app.chatloop.subagent import READONLY_SUBAGENT_TOOLS


def test_readonly_whitelist_excludes_write_and_escalation_and_recursion() -> None:
    forbidden = {
        "memory_write",  # 禁写
        "offer_deep_research",  # 禁串门(漏进研报世界)
        "dispatch_subagents",  # 禁递归(子循环再派子循环)
        "run_skill_script",  # 禁跑会改东西的脚本
        "load_skill",  # 纯检索不需方法论
        "compare_stocks",  # 它自己就是扇出工具,子循环是扇出单元,避免嵌套
    }
    assert forbidden.isdisjoint(set(READONLY_SUBAGENT_TOOLS)), (
        "子循环白名单泄漏了写/升级/递归工具,违反隔离铁律"
    )


def test_whitelist_is_exactly_readonly_data_tools() -> None:
    assert set(READONLY_SUBAGENT_TOOLS) == {
        "get_stock_quote",
        "get_financial_statements",
        "kb_search",
        "get_news",
        "web_search",
        "get_market_indicators",
        "get_corporate_actions",
    }


def test_child_hub_cannot_expose_dispatch_tool() -> None:
    """子 hub 即便给它 registry 里有 dispatch_subagents,register_subset 也只取白名单。"""
    from typing import Any

    from app.chatloop.events import SeqCounter
    from app.chatloop.subagent import build_child_tool_hub

    class _FakeTool:
        def __init__(self, name: str) -> None:
            self.name = name

        def schema_for_llm(self) -> dict[str, Any]:
            return {"type": "function", "function": {"name": self.name, "parameters": {}}}

    class _Reg:
        def list_for_llm(self) -> list[dict[str, Any]]:
            # registry 里"假装"也有 dispatch_subagents / offer_deep_research
            return [
                {"function": {"name": n}}
                for n in (*READONLY_SUBAGENT_TOOLS, "dispatch_subagents", "offer_deep_research")
            ]

        def get(self, name: str) -> Any:
            return _FakeTool(name)

    hub = build_child_tool_hub(_Reg(), emit=None, seq_counter=SeqCounter(), cache=None)
    names = {s["function"]["name"] for s in hub.schemas_for_llm()}
    assert "dispatch_subagents" not in names  # 禁递归
    assert "offer_deep_research" not in names  # 禁串门
    assert names == set(READONLY_SUBAGENT_TOOLS)
