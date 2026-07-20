"""MEMORY.md 等价索引：只投影 DB 元数据，不泄露具体记忆正文。"""

from app.memory.index_projection import render_memory_index


def test_render_memory_index_contains_categories_but_not_details() -> None:
    projection = {
        "working_blocks": [
            {"name": "persona", "token_count": 18},
            {"name": "scratchpad", "token_count": 7},
        ],
        "archival": {
            "total": 3,
            "relations": {"HOLDS": 2, "WATCHES": 1},
            "latest_recorded_at": "2026-07-20T10:00:00+00:00",
        },
    }

    rendered = render_memory_index(projection)

    assert rendered.startswith("## MEMORY.md（数据库投影索引）")
    assert "persona" in rendered and "18 tokens" in rendered
    assert "HOLDS: 2" in rendered and "WATCHES: 1" in rendered
    assert "贵州茅台" not in rendered
    assert "具体记忆请按需调用 memory_search" in rendered
