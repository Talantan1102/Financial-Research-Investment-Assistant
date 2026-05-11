"""L0: render_digest_markdown 纯函数 unit test (Plan 7B Task 7).

不碰 DB; 用 SimpleNamespace 仿 ChatMemoryEdge 的最小字段.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from app.services.memory_email import (
    _empty_digest_template,
    render_digest_markdown,
)


def _mk_edge(
    rel_type: str = "HOLDS",
    importance: float = 0.9,
    valid_from: datetime | None = None,
) -> Any:
    return SimpleNamespace(
        edge_id=uuid4(),
        rel_type=rel_type,
        importance=importance,
        valid_from=valid_from or datetime(2025, 4, 15, tzinfo=UTC),
    )


def test_render_empty_rows_uses_empty_template() -> None:
    body = render_digest_markdown([], "张先生")
    assert "暂无新增 memory" in body
    assert "张先生" in body
    assert "/memory" in body


def test_render_5_rows_lists_in_order() -> None:
    rows = [
        (_mk_edge("HOLDS"), "我", "茅台"),
        (_mk_edge("PREFERS"), "我", "白酒行业"),
        (_mk_edge("AVOIDS"), "我", "新能源"),
    ]
    body = render_digest_markdown(rows, "李四")
    assert "我们最近一个月记下了关于您的 3 件事" in body
    assert "**持仓**: 我 → 茅台" in body
    assert "**偏好**: 我 → 白酒行业" in body
    assert "**回避**: 我 → 新能源" in body
    # 验顺序
    pos_holds = body.index("持仓")
    pos_prefers = body.index("偏好")
    pos_avoids = body.index("回避")
    assert pos_holds < pos_prefers < pos_avoids


def test_render_includes_invalidate_url_per_row() -> None:
    edge = _mk_edge("HOLDS")
    rows = [(edge, "我", "茅台")]
    body = render_digest_markdown(rows, "用户", web_base_url="https://x.com")
    assert f"https://x.com/memory?highlight_edge={edge.edge_id}&action=invalidate" in body
    assert "[一键否决](" in body


def test_render_unknown_rel_type_falls_back_to_raw() -> None:
    rows = [(_mk_edge("UNKNOWN_REL"), "A", "B")]
    body = render_digest_markdown(rows, "用户")
    assert "**UNKNOWN_REL**: A → B" in body


def test_empty_template_links_to_memory() -> None:
    body = _empty_digest_template("用户", "https://x.com")
    assert "https://x.com/memory" in body
