"""L0 — dispatch_subagents 进延迟组 + 有完整文档。"""

from __future__ import annotations

from app.chatloop.tool_docs import DEFERRED_TOOLS, TOOL_DOCS, thin_schema


def test_dispatch_in_deferred_with_doc() -> None:
    assert "dispatch_subagents" in DEFERRED_TOOLS
    assert "dispatch_subagents" in TOOL_DOCS
    doc = TOOL_DOCS["dispatch_subagents"]
    assert doc.group == "deferred"
    # subtasks 必填 → 瘦 schema 暴露它
    assert doc.thin_required is not None
    assert "subtasks" in doc.thin_required


def test_dispatch_thin_schema_has_required() -> None:
    schema = thin_schema(TOOL_DOCS["dispatch_subagents"])
    assert "subtasks" in schema["function"]["parameters"]["required"]
