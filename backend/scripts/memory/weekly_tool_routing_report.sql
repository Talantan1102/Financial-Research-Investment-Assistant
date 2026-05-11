-- C.5 spec § 6 — Memory tool routing weekly report.
-- Plan 4 ship.
--
-- Data source: mcp_tool_call_log (Plan 4 SQLAlchemy model + migration).
-- Run: psql -d $POSTGRES_DB -f weekly_tool_routing_report.sql
--
-- 期望阈值 (spec § 6):
--   archival_memory_search hit > 80%
--   archival_memory_traverse hit > 50%
--   recall_memory_search hit > 70%

-- 1. Per-tool calls + hit rate + p50 / p95 latency + error count (last 7d)
SELECT
    tool_name,
    COUNT(*)                                                AS calls,
    AVG(CASE WHEN result_count > 0 THEN 1.0 ELSE 0.0 END)   AS hit_rate,
    PERCENTILE_DISC(0.5)
        WITHIN GROUP (ORDER BY latency_ms)                  AS p50_latency_ms,
    PERCENTILE_DISC(0.95)
        WITHIN GROUP (ORDER BY latency_ms)                  AS p95_latency_ms,
    SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END)      AS error_count
FROM mcp_tool_call_log
WHERE tool_name LIKE '%memory%'
  AND created_at > now() - interval '7 days'
GROUP BY tool_name
ORDER BY calls DESC;

-- 2. Per-user breakdown (top 10 重度 memory 用户)
SELECT
    user_id,
    COUNT(*)                       AS calls,
    COUNT(DISTINCT tool_name)      AS tools_used
FROM mcp_tool_call_log
WHERE tool_name LIKE '%memory%'
  AND created_at > now() - interval '7 days'
GROUP BY user_id
ORDER BY calls DESC
LIMIT 10;

-- 3. Per-day routing trend (last 14d)
SELECT
    DATE(created_at)               AS day,
    tool_name,
    COUNT(*)                       AS calls
FROM mcp_tool_call_log
WHERE tool_name LIKE '%memory%'
  AND created_at > now() - interval '14 days'
GROUP BY day, tool_name
ORDER BY day DESC, calls DESC;
