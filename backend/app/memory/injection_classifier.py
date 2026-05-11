"""Algorithm 深度补丁 #2 — Memory 投毒 + Agent 幻觉写防御.

Plan 4 ship: minimal evidence_quote_in_episode + EvidenceNotFoundError.
Plan 5 ship: is_prompt_injection (rules layer; ML 留 v1.x P3 hook).

Per shared contract § 17 A6:
    evidence_quote_in_episode minimal version (whitespace-tolerant substring) is
    shipped here by Plan 4. Plan 5 Edits (NOT replaces) this file to add
    is_prompt_injection.

Contracts § 5 spec ref.
"""

from __future__ import annotations

import re

# ============================================================================
# Plan 4 ship — evidence_quote_in_episode + EvidenceNotFoundError (DO NOT MOVE)
# ============================================================================


class EvidenceNotFoundError(ValueError):
    """Agent 调 archival_memory_insert 时 evidence_quote 不在 episode 原文.

    Plan 4 在 archival_memory_insert MCP tool 内 raise; agent 必须改 evidence_quote
    重试. 继承 ValueError 保持调用方 except 兼容性.
    """


class PromptInjectionDetectedError(ValueError):
    """`is_prompt_injection` 命中, write path 拒绝写入.

    Plan 5 自卡声明 archival_memory_insert 写入前过滤 episode 内容, 但实际未接通,
    `is_prompt_injection` 长期是死代码 (S1 fix). 本异常由 4 个写入入口在确认 injection
    后 raise, 阻止任何 working_blocks / graph / Milvus 写入:

      - `archival_memory_insert` MCP tool — episode_text / reasoning / evidence_quote
      - `core_memory_append` MCP tool — content
      - `core_memory_replace` MCP tool — new_content
      - `LLMExtractor.extract` / `extract_facts` — episode_text / turn 文本 (返回空 ExtractionOutput
        而非 raise, 避免阻塞 Path B 整个 chunk)

    继承 ValueError 保持 caller `except ValueError` 兼容. err message 含命中 pattern_id
    给 mcp_tool_call_log audit 用.
    """


def evidence_quote_in_episode(quote: str, episode_text: str) -> bool:
    """Substring 校验 (空白容忍).

    去掉 quote / episode 中的所有连续空白(包括 \\n / \\t / 全角空格), 再做
    substring containment check.

    Examples:
        "买了 500 股" matches "买了500股"
        "我永不碰科技股" does NOT match "今天买了 500 股茅台"

    Returns:
        True iff normalized quote is a non-empty substring of normalized episode.
    """
    if not quote or not quote.strip():
        return False
    q_norm = re.sub(r"\s+", "", quote)
    e_norm = re.sub(r"\s+", "", episode_text or "")
    if not q_norm:
        return False
    return q_norm in e_norm


# ============================================================================
# Plan 5 ship — is_prompt_injection (rules layer)
# ============================================================================

# 高置信度 injection 模式(命中即 confidence=0.95). 设计逻辑:
#   1. 中文模式必须配合"指令/规则/限制/system/角色"等强信号词, 不裸匹配 "忽略"
#   2. 英文模式同样要求 "previous/all/above + instructions/rules/prompts" 上下文
#   3. role-tag 注入(###USER### / [SYSTEM] / </user_input>)直接命中
_HIGH_CONFIDENCE_PATTERNS: list[tuple[str, str]] = [
    # 中文 - 指令撤销 / 角色伪造
    (r"忽略\s*(所有|以上|之前)\s*(指令|规则|限制|prompt)", "zh_ignore_instructions"),
    (
        r"忘记\s*(所有|以前|之前)?[\s之前所有的]*(指令|规则|限制|prompt)",
        "zh_forget_instructions",
    ),
    (r"你\s*现在\s*是\s*(DAN|开发者|无限制)", "zh_role_override"),
    (r"你\s*必须\s*假装", "zh_pretend_role"),
    (r"从\s*现在\s*开始[,，]?\s*(system|系统)\s*[:：是]", "zh_inject_system"),
    # 英文 - 同等模式
    (
        r"ignore\s+(all\s+)?(previous|above|prior)\s+(instructions|rules|prompts)",
        "en_ignore",
    ),
    (r"pretend\s+you\s+are\s+(DAN|unrestricted|jailbroken)", "en_pretend"),
    (r"act\s+as\s+(an\s+)?unrestricted", "en_act_as_unrestricted"),
    (r"\bsystem\s*:\s*(you\s+are\s+now|override|ignore)", "en_inject_system"),
    # role-tag / 标签注入
    (r"###\s*(USER|SYSTEM|ASSISTANT)\s*###", "role_tag_injection"),
    (r"\[\s*(USER|SYSTEM|ASSISTANT)\s*\]", "bracket_role_injection"),
    (r"</\s*\w+\s*>\s*<\s*system", "tag_break_injection"),
]


def is_prompt_injection(text: str) -> tuple[bool, float, str]:
    """Returns (is_injection, confidence, reason).

    spec § 11 末尾 #2:
      - 规则层: 关键词 + 正则匹配, 命中 confidence=0.95, reason=pattern_id
      - ML 层(v1.x P3 hook): 200M 小分类器, confidence < 0.9 时启用
      - 默认安全: 不命中 → (False, 0.0, "no_match")

    用例(Plan 4 / 8 调用):
      - Plan 4 archival_memory_insert 写入前过滤 episode 内容
      - Plan 2 extractor 抽取前过滤 episode_text
    """
    if not text:
        return False, 0.0, "empty"

    for pattern, pid in _HIGH_CONFIDENCE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True, 0.95, pid

    return False, 0.0, "no_match"
