-- C.5 Plan 4 — mcp_tool_call_log 表 (spec § 6 周报 SQL data source)
--
-- 每次 MCP tool 调用 (Plan 4 backend/app/mcp_server/tools/memory/_common.write_tool_call_log)
-- 落一行: tool_name / args / result_count / latency / error.
--
-- 消费方:
--   - backend/scripts/memory/weekly_tool_routing_report.sql — 周度路由报表
--   - Plan 8 eval pipeline — routing accuracy metric 数据来源
--
-- Idempotent: 安全多次运行 (CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS).

CREATE TABLE IF NOT EXISTS mcp_tool_call_log (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       VARCHAR(64) NOT NULL,                                   -- str 兼容 PR #39 trace 习惯
    tool_name     VARCHAR(64) NOT NULL,
    args_json     JSONB NOT NULL DEFAULT '{}'::jsonb,
    result_count  INTEGER NOT NULL DEFAULT 0,
    latency_ms    DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    error         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_mcp_tool_call_log_tool_created
    ON mcp_tool_call_log(tool_name, created_at);

CREATE INDEX IF NOT EXISTS idx_mcp_tool_call_log_user
    ON mcp_tool_call_log(user_id);
