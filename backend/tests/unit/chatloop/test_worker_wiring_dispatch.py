"""L0 — build_turn_components 注册了 dispatch_subagents。"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

import pytest
from app.chatloop.events import SeqCounter
from app.chatloop.gates import GateConfig
from app.chatloop.worker_wiring import HeavySingletons, build_turn_components
from app.tools.get_stock_quote import StockQuoteTool


class _StubRegistry:
    def list_for_llm(self) -> list[dict[str, Any]]:
        return [self._quote.schema_for_llm()]

    def get(self, name: str) -> Any:
        return self._quote if name == self._quote.name else None

    def __init__(self) -> None:
        self._quote = StockQuoteTool()


def _singletons() -> HeavySingletons:
    return HeavySingletons(
        llm=object(),
        registry=_StubRegistry(),
        memory=object(),
        loader=object(),
        executor=object(),
        cache=None,  # type: ignore[arg-type]
        skill_listing="",
        gate_cfg=GateConfig(),
    )


@pytest.mark.asyncio
async def test_dispatch_tool_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _emit(ev: Any) -> None:
        pass

    monkeypatch.setitem(
        sys.modules,
        "resource",
        SimpleNamespace(RLIMIT_AS=0, RLIMIT_DATA=0, RLIMIT_CPU=0, setrlimit=lambda *_: None),
    )
    components = build_turn_components(_singletons(), emit=_emit, seq_counter=SeqCounter())
    schemas = components.tool_hub.schemas_for_llm()
    names = [s["function"]["name"] for s in schemas]
    assert "dispatch_subagents" in names
    assert "get_stock_quote" in names
