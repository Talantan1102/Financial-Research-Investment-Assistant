"""L0 — system prompt template content checks for memory_tool_usage.md.

Plan 4 ships the template; Plan 6 supervisor will load it at chat init.
"""

from __future__ import annotations

from pathlib import Path

PROMPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "app"
    / "agents"
    / "chat"
    / "prompts"
    / "memory_tool_usage.md"
)


def test_template_exists() -> None:
    assert PROMPT_PATH.exists(), f"missing: {PROMPT_PATH}"


def test_template_has_three_tiers() -> None:
    content = PROMPT_PATH.read_text(encoding="utf-8")
    assert "Tier 1" in content
    assert "Tier 2" in content
    assert "Tier 3" in content


def test_template_has_traverse_trigger_words() -> None:
    """Per shared contracts § 8 TRAVERSE_TRIGGER_WORDS."""
    content = PROMPT_PATH.read_text(encoding="utf-8")
    for w in ["相关", "同行业", "之间", "链", "上下游"]:
        assert w in content, f"missing trigger word: {w}"


def test_template_has_hygiene_rules_section() -> None:
    content = PROMPT_PATH.read_text(encoding="utf-8")
    assert "Memory hygiene rules" in content
    rules_section = content[content.index("Memory hygiene rules") :]
    # Counting numbered list items + bullet list items combined
    rule_count = (
        rules_section.count("\n1.")
        + rules_section.count("\n2.")
        + rules_section.count("\n3.")
        + rules_section.count("\n4.")
        + rules_section.count("\n- ")
    )
    assert rule_count >= 4, f"expected ≥4 hygiene rules, got {rule_count}"


def test_template_has_persona_scratchpad_placeholder() -> None:
    content = PROMPT_PATH.read_text(encoding="utf-8")
    assert "{{persona_block}}" in content
    assert "{{scratchpad_block}}" in content


def test_template_describes_six_tools_by_name() -> None:
    content = PROMPT_PATH.read_text(encoding="utf-8")
    for tool in [
        "core_memory_append",
        "core_memory_replace",
        "archival_memory_insert",
        "archival_memory_search",
        "archival_memory_traverse",
        "recall_memory_search",
    ]:
        assert tool in content, f"missing tool description: {tool}"


def test_template_mentions_evidence_quote_constraint() -> None:
    """Algorithm 深度补丁 #2 must surface in agent-facing docs."""
    content = PROMPT_PATH.read_text(encoding="utf-8")
    assert "evidence_quote" in content
    # Must mention substring + reject semantics
    assert "substring" in content.lower() or "原文" in content


def test_template_has_domain_specific_save_triggers() -> None:
    """Plan 1 spec § 6 决策 8 — 金融业务定制 save triggers."""
    content = PROMPT_PATH.read_text(encoding="utf-8")
    # 3 条 domain-specific save triggers
    assert "投资偏好" in content
    assert "加减仓" in content or "HOLDS" in content
    assert "EXPRESSED_VIEW" in content
    # Don't save 反例
    assert "一次性" in content or "闲聊" in content


def test_template_has_dont_save_section() -> None:
    """Phase 1 — 反例避免 agent over-write."""
    content = PROMPT_PATH.read_text(encoding="utf-8")
    # 反例 section 必须存在
    assert "Don't save" in content or "不要 save" in content


def test_template_warns_not_to_modify_user_section() -> None:
    """Plan Task 18 — 双轨保护 prompt 约束 (persona-ui spec § 8.3)."""
    content = PROMPT_PATH.read_text(encoding="utf-8")
    assert "不要试图修改" in content
    assert "你声明的" in content
