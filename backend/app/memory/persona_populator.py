"""Working Memory Auto-Injection — spec § 5 末尾 + § 7.

每 session 起手扫 4 类 edge(HOLDS / PREFERS / AVOIDS / WATCHES current snapshot)
→ 生成 markdown ~500 tokens → UPSERT working_blocks(persona).

调用方: chat router session-start hook (Plan 3 改 router 接入).

设计取舍:
- sync Session pattern: 跟 HierarchicalMemory.core_memory_append 同 transaction model.
- session_factory(callable) 入参一致 HierarchicalMemory DI 接口(契约 § 3).
- 失败语义: 内部不吞异常, caller 用 try/except 包装(避免阻塞 session create).
- char-based truncate(_TOKEN_PER_CHAR_RATIO=1.4)避免装 tiktoken 依赖.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

# C65/C63: PERSONA_BLOCK_NAME and token budget imported from working_blocks (SSOT).
from app.memory.working_blocks import BLOCK_DEFAULTS, PERSONA_BLOCK_NAME

logger = logging.getLogger(__name__)

# C63: keep the public name so callers importing PERSONA_MAX_TOKENS are unaffected,
# but derive the value from BLOCK_DEFAULTS so tuning BLOCK_DEFAULTS stays in sync.
PERSONA_MAX_TOKENS: int = BLOCK_DEFAULTS[PERSONA_BLOCK_NAME]
# 中文 ≈ 1.33 tokens/char, 留 buffer 取 1.4
_TOKEN_PER_CHAR_RATIO: float = 1.4


def format_persona_markdown(
    holdings: list[dict[str, Any]],
    preferences: list[dict[str, Any]],
    avoids: list[dict[str, Any]],
    watches: list[dict[str, Any]],
) -> str:
    """spec § 5 末尾 实例: 4 类 + ~500 tokens markdown."""
    parts: list[str] = ["## 用户画像（auto-generated from memory graph）"]

    # 持仓
    parts.append("\n### 当前持仓")
    if holdings:
        for h in holdings:
            label = h.get("ts_code") or h.get("label", "?")
            qty = h.get("qty")
            since = h.get("since")
            thesis = h.get("thesis")
            line = f"- {label}"
            details: list[str] = []
            if since:
                details.append(f"since {since}")
            if qty:
                details.append(f"qty={qty}")
            if thesis:
                details.append(f"thesis: {thesis}")
            if details:
                line += " (" + ", ".join(details) + ")"
            parts.append(line)
    else:
        parts.append("- 暂无")

    # 偏好
    parts.append("\n### 偏好方法（PREFERS）")
    if preferences:
        for p in preferences:
            label = p.get("label") or p.get("ts_code", "?")
            prio = p.get("priority")
            line = f"- {label}"
            if prio is not None:
                line += f" (priority {prio})"
            parts.append(line)
    else:
        parts.append("- 暂无")

    # 规避
    parts.append("\n### 规避")
    if avoids:
        for a in avoids:
            label = a.get("label") or a.get("ts_code", "?")
            reason = a.get("reason")
            line = f"- {label}"
            if reason:
                line += f" ({reason})"
            parts.append(line)
    else:
        parts.append("- 暂无")

    # 关注
    parts.append("\n### 关注但未持仓")
    if watches:
        labels = [w.get("ts_code") or w.get("label", "?") for w in watches]
        parts.append("- " + ", ".join(labels))
    else:
        parts.append("- 暂无")

    md = "\n".join(parts)
    return _truncate_to_token_budget(md, max_tokens=PERSONA_MAX_TOKENS)


def _truncate_to_token_budget(text_in: str, max_tokens: int) -> str:
    """简单 char-based 截断 + buffer.

    Plan 3 ship 时不装 tiktoken; 用 1.4 tokens/char 估算 char_budget.
    """
    char_budget = int(max_tokens / _TOKEN_PER_CHAR_RATIO)
    if len(text_in) <= char_budget:
        return text_in
    suffix = "\n... [truncated]"
    cutoff = max(0, char_budget - len(suffix))
    return text_in[:cutoff] + suffix


def _extract_edge_dict(row: Any) -> dict[str, Any]:
    """row → flat dict, 把 properties JSONB 展开."""
    if hasattr(row, "_mapping"):
        d = dict(row._mapping)
    elif isinstance(row, dict):
        d = dict(row)
    else:
        d = dict(row)
    props = d.pop("props", None) or {}
    out = dict(d)
    if isinstance(props, dict):
        for k in ("qty", "since", "thesis", "priority", "reason"):
            if k in props and k not in out:
                out[k] = props[k]
    return out


def populate_persona_on_session_start(
    pg_session_factory: Callable[[], Session],
    user_id: UUID,
) -> None:
    """spec § 5 末尾完整实现 — session 起手 hook 入口.

    sync session pattern, caller 包 try/except 防 session 创建失败.

    UPSERT 走 ON CONFLICT (user_id, block_name) → uq_working_blocks_user_name 唯一约束.

    persona-ui Task 17/21 integration: items table is source of truth for users
    who've engaged with /memory UI. Skip auto-populate to avoid overwriting
    items-sourced content. Cold-start (no items yet) users still enjoy the legacy
    graph-edge auto-populate behavior.
    """
    # Guard: if the user already has persona items, the items table is the source
    # of truth. PersonaService._sync_to_working_block handles writes there.
    # Proceeding would race-overwrite items-sourced content.
    from app.memory.models import ChatMemoryPersonaItem  # local import avoids circular dep

    session = pg_session_factory()
    try:
        item_count = session.query(ChatMemoryPersonaItem).filter_by(user_id=user_id).count()
    finally:
        session.close()

    if item_count > 0:
        logger.debug(
            "persona populator skipped for user %s — %d items present (items table is source of truth)",
            user_id,
            item_count,
        )
        return

    session = pg_session_factory()
    try:
        holdings_rows = session.execute(
            text(
                """
                SELECT n.entity_label AS ts_code,
                       e.properties AS props,
                       e.valid_from AS since
                FROM chat_memory_edges e
                JOIN chat_memory_nodes n ON e.target_node_id = n.node_id
                WHERE e.user_id = :uid
                  AND e.rel_type = 'HOLDS'
                  AND e.valid_to IS NULL
                  AND e.invalidated_at IS NULL
                ORDER BY e.valid_from DESC
                LIMIT 20
                """
            ),
            {"uid": str(user_id)},
        ).fetchall()
        holdings = [_extract_edge_dict(r) for r in holdings_rows]

        prefs_rows = session.execute(
            text(
                """
                SELECT n.entity_label AS label, e.properties AS props
                FROM chat_memory_edges e
                JOIN chat_memory_nodes n ON e.target_node_id = n.node_id
                WHERE e.user_id = :uid
                  AND e.rel_type = 'PREFERS'
                  AND e.valid_to IS NULL
                  AND e.invalidated_at IS NULL
                ORDER BY (e.properties->>'priority')::float DESC NULLS LAST
                LIMIT 10
                """
            ),
            {"uid": str(user_id)},
        ).fetchall()
        preferences = [_extract_edge_dict(r) for r in prefs_rows]

        avoids_rows = session.execute(
            text(
                """
                SELECT n.entity_label AS label, e.properties AS props
                FROM chat_memory_edges e
                JOIN chat_memory_nodes n ON e.target_node_id = n.node_id
                WHERE e.user_id = :uid
                  AND e.rel_type = 'AVOIDS'
                  AND e.valid_to IS NULL
                  AND e.invalidated_at IS NULL
                LIMIT 10
                """
            ),
            {"uid": str(user_id)},
        ).fetchall()
        avoids = [_extract_edge_dict(r) for r in avoids_rows]

        watches_rows = session.execute(
            text(
                """
                SELECT n.entity_label AS label
                FROM chat_memory_edges e
                JOIN chat_memory_nodes n ON e.target_node_id = n.node_id
                WHERE e.user_id = :uid
                  AND e.rel_type = 'WATCHES'
                  AND e.valid_to IS NULL
                  AND e.invalidated_at IS NULL
                LIMIT 20
                """
            ),
            {"uid": str(user_id)},
        ).fetchall()
        watches = [_extract_edge_dict(r) for r in watches_rows]

        md = format_persona_markdown(holdings, preferences, avoids, watches)
        token_count = int(len(md) * _TOKEN_PER_CHAR_RATIO)

        session.execute(
            text(
                """
                INSERT INTO chat_memory_working_blocks
                    (block_id, user_id, block_name, content, token_count, max_tokens, updated_at)
                VALUES (gen_random_uuid(), :uid, :bn, :content, :tc, :max_tc, now())
                ON CONFLICT (user_id, block_name) DO UPDATE SET
                    content = EXCLUDED.content,
                    token_count = EXCLUDED.token_count,
                    updated_at = now()
                """
            ),
            {
                "uid": str(user_id),
                "bn": PERSONA_BLOCK_NAME,
                "content": md,
                "tc": token_count,
                "max_tc": PERSONA_MAX_TOKENS,
            },
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
