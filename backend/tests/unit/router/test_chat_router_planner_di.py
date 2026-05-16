"""L0 — chat router 实例化 ChatPlanner 时传 memory DI.

Phase 1 self-managed memory wire 完整闭环守护:
- ChatPlanner.__init__ 接 memory param (Task 4 已加)
- chat router _build_graph_singleton 传 memory=memory (Task 6 本次)

如果未来 refactor 误删 memory= kwarg, 这俩测试会红.
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock

from app.agents.chat_planner import ChatPlanner


def test_chat_planner_init_accepts_memory_param() -> None:
    """Phase 1 wire 守护 — ChatPlanner.__init__ 必须有 memory 参数."""
    sig = inspect.signature(ChatPlanner.__init__)
    assert "memory" in sig.parameters
    # default 应该是 None (向后兼容)
    assert sig.parameters["memory"].default is None


def test_chat_planner_stores_memory() -> None:
    """memory 必须挂在 instance 上 (chat 节点能读)."""
    planner = ChatPlanner(llm=MagicMock(), memory="<sentinel>")  # type: ignore[arg-type]
    assert planner._memory == "<sentinel>"


def test_chat_router_passes_memory_to_planner() -> None:
    """router._build_graph_singleton 必须把 memory= 传到 ChatPlanner.

    通过源码 grep 检查 (避免 import 真 LLM/DB DI 副作用).
    """
    import re
    from pathlib import Path

    router_path = Path(__file__).resolve().parents[3] / "app" / "router" / "chat.py"
    source = router_path.read_text(encoding="utf-8")

    # 找到 _build_graph_singleton 函数体内的 ChatPlanner( 调用
    match = re.search(
        r"def _build_graph_singleton.*?(?=\ndef |\Z)",
        source,
        re.DOTALL,
    )
    assert match is not None, "_build_graph_singleton not found"
    body = match.group(0)

    # 检查 ChatPlanner( ... memory=memory ... ) 调用形态
    chat_planner_calls = re.findall(r"ChatPlanner\([^)]*\)", body)
    assert len(chat_planner_calls) >= 1, "no ChatPlanner( call found in _build_graph_singleton"
    assert any("memory=memory" in call for call in chat_planner_calls), (
        f"ChatPlanner instantiation in _build_graph_singleton missing memory=memory; "
        f"got: {chat_planner_calls}"
    )
