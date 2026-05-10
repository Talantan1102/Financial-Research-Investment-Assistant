"""Monthly memory digest email body generator (Plan 7B Task 7).

#8 算法深度补丁 (c) — spec § 11 末尾: 每月推 "我们记得关于您的 5 件事,
请确认" 邮件, 一键否决回链 /memory page.

**Plan 7B 范围**:
    - render_digest_markdown(rows, name) → markdown body 纯函数
    - fetch_top_edges_for_digest(session, user_id, ...) → DB 查询
    - generate_monthly_digest(session, user_id, ...) → public entry

**Plan 7B 不在范围 (留 P3 hook)**:
    - 实际邮件发送 (SMTP/SendGrid) → P3 worker (Celery monthly cron)
    - unsubscribe / 关闭月度 digest UI → P3 邮件回路

P3 hook ref: ``backend/app/tasks/memory_email_worker.py`` (Celery monthly cron)
调本模块 ``generate_monthly_digest`` 后接 send_email().
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select

from app.memory.models import ChatMemoryEdge, ChatMemoryNode

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

REL_TYPE_LABELS_ZH: dict[str, str] = {
    "HOLDS": "持仓",
    "WATCHES": "关注",
    "PREFERS": "偏好",
    "AVOIDS": "回避",
    "EXPRESSED_VIEW": "表态",
    "SOLD": "卖出",
    "STUDIED": "研究",
    "COMPARED": "对比",
    "BELONGS_TO": "属于",
    "HAS_CONCEPT": "含概念",
    "CORRELATED_WITH": "相关",
}

DEFAULT_TOP_N = 5
DEFAULT_WINDOW_DAYS = 30
WEB_BASE_URL_DEFAULT = "https://app.local"


# ---------------------------------------------------------------------------
# DB 查询
# ---------------------------------------------------------------------------


def fetch_top_edges_for_digest(
    session: Session,
    user_id: UUID,
    top_n: int = DEFAULT_TOP_N,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> list[tuple[ChatMemoryEdge, str, str]]:
    """取该 user 最近 ``window_days`` 内 importance DESC 前 ``top_n`` 条 current edge.

    过滤条件 (spec § 11 #8 c "current 仅"):
        - ``valid_to IS NULL`` (未结束)
        - ``invalidated_at IS NULL`` (未被否决)
        - ``recorded_at >= cutoff``

    排序:
        - importance DESC (高重要在前)
        - recorded_at DESC (同等 importance 取最近)

    Returns:
        ``[(edge, source_label, target_label), ...]``
    """
    cutoff = datetime.now(UTC) - timedelta(days=window_days)

    src = ChatMemoryNode.__table__.alias("src")
    tgt = ChatMemoryNode.__table__.alias("tgt")
    e = ChatMemoryEdge.__table__

    stmt = (
        select(
            ChatMemoryEdge,
            src.c.entity_label.label("src_label"),
            tgt.c.entity_label.label("tgt_label"),
        )
        .select_from(
            e.join(src, e.c.source_node_id == src.c.node_id).join(
                tgt, e.c.target_node_id == tgt.c.node_id
            )
        )
        .where(e.c.user_id == user_id)
        .where(e.c.valid_to.is_(None))
        .where(e.c.invalidated_at.is_(None))
        .where(e.c.recorded_at >= cutoff)
        .order_by(e.c.importance.desc().nullslast(), e.c.recorded_at.desc())
        .limit(top_n)
    )

    result = session.execute(stmt)
    rows = result.all()
    return [(r[0], r.src_label, r.tgt_label) for r in rows]


# ---------------------------------------------------------------------------
# Markdown 渲染 (纯函数, L0 unit test 主体)
# ---------------------------------------------------------------------------


def render_digest_markdown(
    rows: list[tuple[ChatMemoryEdge, str, str]],
    user_display_name: str,
    web_base_url: str = WEB_BASE_URL_DEFAULT,
) -> str:
    """Render markdown email body.

    Empty rows → 空 digest 模板 (走 ``_empty_digest_template``).

    Layout:
        ## {name} 您好, 我们最近一个月记下了关于您的 {n} 件事
        请花 30 秒确认 (任何不准确请一键否决):
        1. **{rel_zh}**: {src} → {tgt} (importance {imp}, {date}) [一键否决]({invalidate_url})
        ...
        [查看完整 memory]({memory_url})

        ---
        如不希望再收到此邮件 ...
    """
    if not rows:
        return _empty_digest_template(user_display_name, web_base_url)

    lines: list[str] = [
        f"## {user_display_name} 您好, 我们最近一个月记下了关于您的 {len(rows)} 件事",
        "",
        "请花 30 秒确认 (任何不准确请一键否决):",
        "",
    ]
    for i, (edge, src_label, tgt_label) in enumerate(rows, start=1):
        # ORM 实例的 column attr 在 mypy 下被推 Column[str], 显式转 str.
        rel_type: str = str(edge.rel_type)
        rel_zh = REL_TYPE_LABELS_ZH.get(rel_type, rel_type)
        valid_from = edge.valid_from
        date_str = valid_from.strftime("%Y-%m-%d") if valid_from is not None else "—"
        invalidate_url = f"{web_base_url}/memory?highlight_edge={edge.edge_id}&action=invalidate"
        lines.append(
            f"{i}. **{rel_zh}**: {src_label} → {tgt_label} "
            f"(importance {edge.importance}, {date_str}) "
            f"[一键否决]({invalidate_url})"
        )
    lines.extend(
        [
            "",
            f"[查看完整 memory]({web_base_url}/memory)",
            "",
            "---",
            "如不希望再收到此邮件, 在 /memory 页底部关闭月度 digest.",
        ]
    )
    return "\n".join(lines)


def _empty_digest_template(user_display_name: str, web_base_url: str) -> str:
    return (
        f"## {user_display_name} 您好, 这个月暂无新增 memory\n\n"
        f"看起来这个月您没怎么聊投资 — 之前的记录都还在 "
        f"[/memory]({web_base_url}/memory) 页。\n"
    )


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


def generate_monthly_digest(
    session: Session,
    user_id: UUID,
    user_display_name: str = "用户",
    top_n: int = DEFAULT_TOP_N,
    window_days: int = DEFAULT_WINDOW_DAYS,
    web_base_url: str = WEB_BASE_URL_DEFAULT,
) -> str:
    """Public entry: 拉数据 + 渲染 markdown body.

    P3 hook: 邮件 worker 调本函数后接 SMTP/SendGrid send.
    Plan 7B 只 ship 此函数, 不 ship 实际发送 (留 P3 跟 Scale-2 用户回路一起做).
    """
    rows = fetch_top_edges_for_digest(session, user_id, top_n, window_days)
    return render_digest_markdown(rows, user_display_name, web_base_url)
