from __future__ import annotations

from typing import Any

from app.chatloop.events import SeqCounter
from app.chatloop.gates import GateConfig
from app.chatloop.worker_wiring import HeavySingletons, build_turn_components


class _Registry:
    def list_for_llm(self) -> list[dict[str, Any]]:
        return []


class _PaperDependencies:
    async def dispatch(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {}


def _singletons() -> HeavySingletons:
    return HeavySingletons(
        llm=object(),
        registry=_Registry(),
        memory=object(),
        loader=object(),
        executor=object(),
        cache=None,  # type: ignore[arg-type]
        skill_listing="",
        gate_cfg=GateConfig(),
        paper_dependencies=_PaperDependencies(),
    )


async def _emit(_event: Any) -> None:
    return None


def test_turn_hub_registers_paper_trade() -> None:
    components = build_turn_components(_singletons(), emit=_emit, seq_counter=SeqCounter())
    names = [schema["function"]["name"] for schema in components.tool_hub.schemas_for_llm()]
    assert "paper_trade" in names
