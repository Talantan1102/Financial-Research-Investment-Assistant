"""markdown ↔ persona items 纯函数测试 — Plan Task 2.

spec § 4.3 渲染契约：固定中文 H2 `## 你声明的` / `## agent 观察到的`，
section 内 `- bullet` 一行一 item。
"""

from __future__ import annotations

import pytest
from app.memory.persona_items_md import parse_markdown_to_drafts, render_items_to_markdown


@pytest.mark.unit
def test_render_empty_sections() -> None:
    md = render_items_to_markdown(user_items=[], agent_items=[])
    assert "## 你声明的" in md
    assert "## agent 观察到的" in md
    assert "_（暂无）_" in md  # 空 section 占位


@pytest.mark.unit
def test_render_only_user_items() -> None:
    md = render_items_to_markdown(
        user_items=["金融研究员", "保守稳健"],
        agent_items=[],
    )
    assert "- 金融研究员" in md
    assert "- 保守稳健" in md
    user_idx = md.index("## 你声明的")
    agent_idx = md.index("## agent 观察到的")
    assert user_idx < agent_idx


@pytest.mark.unit
def test_render_only_agent_items() -> None:
    md = render_items_to_markdown(
        user_items=[],
        agent_items=["关注新能源"],
    )
    assert "- 关注新能源" in md


@pytest.mark.unit
def test_parse_legacy_blob_no_headers() -> None:
    """老 blob 无 H2 → 全部当 agent 区."""
    blob = "- 持有茅台 2000 股\n- 关注高股息板块\n"
    drafts = parse_markdown_to_drafts(blob)
    assert len(drafts) == 2
    assert all(d.source == "agent" for d in drafts)
    assert drafts[0].text == "持有茅台 2000 股"
    assert drafts[1].text == "关注高股息板块"


@pytest.mark.unit
def test_parse_with_headers() -> None:
    blob = "## 你声明的\n- 金融研究员\n\n## agent 观察到的\n- 关注新能源\n- 偏好高股息\n"
    drafts = parse_markdown_to_drafts(blob)
    assert [d.source for d in drafts] == ["user", "agent", "agent"]
    assert [d.text for d in drafts] == [
        "金融研究员",
        "关注新能源",
        "偏好高股息",
    ]


@pytest.mark.unit
def test_parse_empty_blob() -> None:
    assert parse_markdown_to_drafts("") == []
    assert parse_markdown_to_drafts("   \n  ") == []


@pytest.mark.unit
def test_parse_skips_blank_lines_and_non_bullets() -> None:
    blob = "## 你声明的\n\n备注内容（不是 bullet）\n- 风险偏好稳健\n"
    drafts = parse_markdown_to_drafts(blob)
    assert len(drafts) == 1
    assert drafts[0].source == "user"
    assert drafts[0].text == "风险偏好稳健"


@pytest.mark.unit
def test_render_text_with_special_chars() -> None:
    md = render_items_to_markdown(
        user_items=["持仓: 茅台 (2000股) - 2026/03"],
        agent_items=[],
    )
    assert "持仓: 茅台 (2000股) - 2026/03" in md


@pytest.mark.unit
def test_parse_bullet_with_prefix_star() -> None:
    """支持 `* ` prefix（agent 可能输出 * 而非 -）."""
    blob = "* 看好科技股"
    drafts = parse_markdown_to_drafts(blob)
    assert drafts[0].text == "看好科技股"
    assert drafts[0].source == "agent"  # 无 H2 默认 agent
