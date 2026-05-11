-- C.5 Plan 3 — Instrumentation 表
-- 用途:
--   1. chat_memory_retrieval_logs — 长尾召回监控 + posterior calibration 命中数累积
--   2. chat_memory_retrieval_feedback — 用户否决信号 (/memory page invalidate / reject)
--
-- 消费方:
--   - Plan 3 long_tail_monitor.py — top-5 valid_from P90 日级监控
--   - Plan 5 posterior_calibration.py weekly job — 行为信号反向调 importance
--   - Plan 8 eval pipeline — recall_precision metric 引用 retrieved_edge_ids
--
-- 表名严守 § 17 A4: chat_memory_retrieval_logs / chat_memory_retrieval_feedback.
--
-- Idempotent: 安全多次运行 (CREATE TABLE IF NOT EXISTS).

-- ===========================================================================
-- 1. chat_memory_retrieval_logs — 每次 archival_memory_search 落库一行
-- ===========================================================================

CREATE TABLE IF NOT EXISTS chat_memory_retrieval_logs (
    log_id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                     UUID NOT NULL,                                  -- 多租户隔离, 不加 FK 兼容测试 db
    query_text                  TEXT NOT NULL,
    retrieved_edge_ids          JSONB NOT NULL DEFAULT '[]'::jsonb,             -- ordered list
    rrf_scores                  JSONB NOT NULL DEFAULT '{}'::jsonb,             -- {edge_id: score}
    top_k_valid_from_p90_days   FLOAT,                                           -- 长尾监控用
    retriever_breakdown         JSONB,                                           -- {bm25: 10, vector: 10, graph: 0}
    latency_ms                  INTEGER,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_retrieval_logs_user_created
    ON chat_memory_retrieval_logs(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_retrieval_logs_created
    ON chat_memory_retrieval_logs(created_at DESC);

-- ===========================================================================
-- 2. chat_memory_retrieval_feedback — 用户 reject / confirm / invalidate 信号
-- ===========================================================================

CREATE TABLE IF NOT EXISTS chat_memory_retrieval_feedback (
    feedback_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL,
    edge_id         UUID NOT NULL REFERENCES chat_memory_edges(edge_id) ON DELETE CASCADE,
    feedback_kind   VARCHAR(32) NOT NULL,
    reason          TEXT,
    log_id          UUID REFERENCES chat_memory_retrieval_logs(log_id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_retrieval_feedback_kind
        CHECK (feedback_kind IN ('reject', 'confirm', 'invalidate'))
);

CREATE INDEX IF NOT EXISTS idx_retrieval_feedback_user_edge
    ON chat_memory_retrieval_feedback(user_id, edge_id);

CREATE INDEX IF NOT EXISTS idx_retrieval_feedback_created
    ON chat_memory_retrieval_feedback(created_at DESC);
