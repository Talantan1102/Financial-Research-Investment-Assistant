"""L0 — build_turn_components 注册了 dispatch_subagents。"""

from __future__ import annotations

from typing import Any

import pytest
from app.chatloop.events import SeqCounter
from app.chatloop.gates import GateConfig
from app.chatloop.worker_wiring import HeavySingletons, build_turn_components


class _StubRegistry:
    def list_for_llm(self) -> list[dict[str, Any]]:
        return []

    def get(self, name: str) -> Any:
        return None


def _singletons() -> HeavySingletons:
    return HeavySingletons(
        llm=object(), registry=_StubRegistry(), memory=object(), loader=object(),
        executor=object(), cache=None, skill_listing="", gate_cfg=GateConfig(),
    )


@pytest.mark.asyncio
async def test_dispatch_tool_registered() -> None:
    async def _emit(ev: Any) -> None:
        pass

    components = build_turn_components(_singletons(), emit=_emit, seq_counter=SeqCounter())
    schemas = components.tool_hub.schemas_for_llm()
    names = [s["function"]["name"] for s in schemas]
    assert "dispatch_subagents" in names
