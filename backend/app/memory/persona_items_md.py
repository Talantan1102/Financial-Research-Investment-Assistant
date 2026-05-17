"""markdown ↔ persona items 纯函数转换层.

spec § 4.3 渲染契约：固定中文 H2 `## 你声明的` / `## agent 观察到的`，
section 内 `- bullet` 一行一 item。

无 DB / DI 依赖 — PersonaService 用此层做 render_to_markdown 同步 working_block，
migration script 用 parse_markdown_to_drafts 把老 blob 拆成 items。
"""

from __future__ import annotations

from dataclasses import dataclass

HEADER_USER = "## 你声明的"
HEADER_AGENT = "## agent 观察到的"
_EMPTY_PLACEHOLDER = "_（暂无）_"


@dataclass(frozen=True)
class ItemDraft:
    """parse 结果，不带 id（migration / 首次写入由 PersonaService 分配 UUID）."""

    text: str
    source: str  # 'user' / 'agent'
    position: int


def render_items_to_markdown(*, user_items: list[str], agent_items: list[str]) -> str:
    """渲染两个 section 为固定格式 markdown。

    空 section 仍渲染 heading + `_（暂无）_` 占位（让 ChatPlanner prompt
    看到稳定结构，prefix cache 友好）。
    """

    def _section(header: str, items: list[str]) -> str:
        if not items:
            return f"{header}\n{_EMPTY_PLACEHOLDER}"
        bullet_lines = "\n".join(f"- {t}" for t in items)
        return f"{header}\n{bullet_lines}"

    return _section(HEADER_USER, user_items) + "\n\n" + _section(HEADER_AGENT, agent_items)


def parse_markdown_to_drafts(blob: str) -> list[ItemDraft]:
    """解析老 blob 为 drafts；无 H2 → 全部 source='agent'.

    rules:
    - 仅识别 `- ` 或 `* ` 开头的 bullet；其他行（heading / 空行 / 备注）跳过
    - position 在每个 section 内独立从 0 起编
    - placeholder `_（暂无）_` 不算 item
    """

    if not blob or not blob.strip():
        return []

    drafts: list[ItemDraft] = []
    current_source = "agent"
    user_pos = 0
    agent_pos = 0
    saw_any_header = False

    for raw_line in blob.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line == HEADER_USER:
            current_source = "user"
            saw_any_header = True
            continue
        if line == HEADER_AGENT:
            current_source = "agent"
            saw_any_header = True
            continue

        if line == _EMPTY_PLACEHOLDER:
            continue

        if line.startswith("- ") or line.startswith("* "):
            text = line[2:].strip()
        else:
            continue

        if not text:
            continue

        if saw_any_header and current_source == "user":
            drafts.append(ItemDraft(text=text, source="user", position=user_pos))
            user_pos += 1
        else:
            drafts.append(ItemDraft(text=text, source="agent", position=agent_pos))
            agent_pos += 1

    return drafts
