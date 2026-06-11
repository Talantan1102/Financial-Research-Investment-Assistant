"""L0 — ToolHub flat-schema 模式 + register_subset(子循环只读 hub 基建)。"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from app.chatloop.tool_hub import ToolHub
from app.tools.base import Tool


class _QuoteArgs(BaseModel):
    ts_code: str


class _FakeTool(Tool):
    def __init__(self, name: str) -> None:
        self.name = name
        self.description = f"fake {name}"
        self.args_schema = _QuoteArgs

    async def run(self, args: BaseModel) -> dict[str, Any]:
        return {"ok": True}


class _FakeRegistry:
    def __init__(self, names: list[str]) -> None:
        self._tools = {n: _FakeTool(n) for n in names}

    def list_for_llm(self) -> list[dict[str, Any]]:
        return [{"function": {"name": n}} for n in self._tools]

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)


def test_register_subset_only_registers_named() -> None:
    reg = _FakeRegistry(["get_stock_quote", "get_news", "compare_stocks"])
    hub = ToolHub(progressive=False)
    hub.register_subset(reg, ["get_stock_quote", "get_news"])
    schemas = hub.schemas_for_llm()
    names = [s["function"]["name"] for s in schemas]
    assert names == ["get_stock_quote", "get_news"]  # 不含 compare_stocks


def test_flat_mode_no_search_tools_full_schema() -> None:
    # progressive=False:不追加 search_tools,且每个工具出完整 schema(有 properties)
    reg = _FakeRegistry(["get_stock_quote"])
    hub = ToolHub(progressive=False)
    hub.register_subset(reg, ["get_stock_quote"])
    schemas = hub.schemas_for_llm()
    assert all(s["function"]["name"] != "search_tools" for s in schemas)
    params = schemas[0]["function"]["parameters"]
    assert "ts_code" in params["properties"]  # 完整 schema,非瘦条目


def test_register_subset_dup_fail_loud() -> None:
    reg = _FakeRegistry(["get_stock_quote"])
    hub = ToolHub(progressive=False)
    hub.register_subset(reg, ["get_stock_quote"])
    with pytest.raises(ValueError):
        hub.register_subset(reg, ["get_stock_quote"])
