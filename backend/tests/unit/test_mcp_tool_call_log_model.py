"""L0 — MCPToolCallLog table schema test.

Plan 4 ship: SQLAlchemy table for spec § 6 weekly tool routing report SQL.
"""

from __future__ import annotations


def test_mcp_tool_call_log_columns_exist() -> None:
    from app.services.trace_models import MCPToolCallLog

    cols = {c.name for c in MCPToolCallLog.__table__.columns}
    expected = {
        "id",
        "user_id",
        "tool_name",
        "args_json",
        "result_count",
        "latency_ms",
        "error",
        "created_at",
    }
    assert expected.issubset(cols), f"missing cols: {expected - cols}"


def test_mcp_tool_call_log_indexes() -> None:
    from app.services.trace_models import MCPToolCallLog

    # 周报 SQL 按 tool_name + created_at 过滤; per-user 报表 按 user_id 过滤
    idxs = list(MCPToolCallLog.__table__.indexes)
    has_tool_idx = any(any(c.name == "tool_name" for c in idx.columns) for idx in idxs)
    has_user_idx = any(any(c.name == "user_id" for c in idx.columns) for idx in idxs)
    assert has_tool_idx, "missing index on tool_name (weekly SQL needs)"
    assert has_user_idx, "missing index on user_id (per-user report needs)"


def test_mcp_tool_call_log_table_name() -> None:
    from app.services.trace_models import MCPToolCallLog

    assert MCPToolCallLog.__tablename__ == "mcp_tool_call_log"
