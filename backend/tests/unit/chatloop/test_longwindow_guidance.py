"""守护 agent 面向文档不回退:长窗口取数引导走 ref/data_refs,不再教"分段/260 截断"。"""

from __future__ import annotations

from app.chatloop.system_prompt import CHAT_SYSTEM_PROMPT
from app.chatloop.tool_docs import TOOL_DOCS


def test_get_daily_doc_steers_to_data_refs_not_chunking() -> None:
    doc = TOOL_DOCS["get_daily"].doc
    assert "data_refs" in doc  # 指向沙箱引用取全量
    assert "260" not in doc  # 旧"单次最多 260 超出截断"话术已移除(它是分段源头)


def test_system_prompt_has_longwindow_ref_rule() -> None:
    assert "data_refs" in CHAT_SYSTEM_PROMPT  # 长窗口指标走引用算全量的规矩在位
