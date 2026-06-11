"""L0 — dispatch_subagents 进核心组 + 有完整文档。

核心组(非延迟):浏览器 e2e 实测发现 deferred 下模型逐只串行查、从不扇出,且 thin
条目不暴露 subtasks 项结构(goal/target/...)无从填。故升 core,完整 schema 常驻
(spec §14 开放问题"核心 vs 延迟"由 e2e 定为核心;与 run_python 同款 verify 驱动修正)。
"""

from __future__ import annotations

from app.chatloop.tool_docs import CORE_TOOLS, DEFERRED_TOOLS, TOOL_DOCS


def test_dispatch_in_core_with_doc() -> None:
    assert "dispatch_subagents" in CORE_TOOLS
    assert "dispatch_subagents" not in DEFERRED_TOOLS
    assert "dispatch_subagents" in TOOL_DOCS
    doc = TOOL_DOCS["dispatch_subagents"]
    assert doc.group == "core"
    # core 组:常驻完整 schema,不走 thin 条目(模型才看得见 subtasks 项结构)
    assert doc.thin_required is None


def test_dispatch_doc_describes_subtask_fields() -> None:
    # 完整文档须说明 subtasks 项的字段(goal 等),模型才会正确填充
    doc = TOOL_DOCS["dispatch_subagents"].doc
    assert "goal" in doc
    assert "subtasks" in doc
