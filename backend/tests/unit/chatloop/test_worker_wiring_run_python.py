"""run_python 注册进 turn ToolHub 的 L0 测试。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.chatloop.events import SeqCounter
from app.chatloop.gates import GateConfig
from app.chatloop.worker_wiring import HeavySingletons, build_turn_components
from app.skills.skill_executor import SkillExecutor


class _EmptyRegistry:
    def list_for_llm(self) -> list[dict[str, Any]]:
        return []

    def get(self, name: str) -> Any:  # pragma: no cover
        raise KeyError(name)


@pytest.mark.asyncio
async def test_run_python_registered(tmp_path: Path) -> None:
    singletons = HeavySingletons(
        llm=object(),
        registry=_EmptyRegistry(),
        memory=object(),
        loader=object(),
        executor=SkillExecutor(skills_root=tmp_path / "s", workdir_root=tmp_path / "wd"),
        cache=None,
        skill_listing="## 可用技能",
        gate_cfg=GateConfig(),
    )

    async def _emit(_ev: Any) -> None:  # noqa: ANN401
        return None

    comp = build_turn_components(singletons, emit=_emit, seq_counter=SeqCounter())
    names = [s["function"]["name"] for s in comp.tool_hub.schemas_for_llm()]
    assert "run_python" in names
