-- C.5 Plan 2A: Milvus outbox table.
-- 写入 pipeline Step 7 Milvus 失败时写入这里, Plan 2B Celery job 5min 扫一次重试。
-- 算法深度补丁 #5 三方一致性: PG 主事务 + outbox 兜底 + reconciliation。
--
-- Idempotent.

CREATE TABLE IF NOT EXISTS pending_milvus_inserts (
    id              BIGSERIAL PRIMARY KEY,
    edge_id         UUID NOT NULL REFERENCES chat_memory_edges(edge_id) ON DELETE CASCADE,
    edge_text       TEXT NOT NULL,                  -- spec § 2 embed text 模板已格式化
    user_id         UUID NOT NULL,
    rel_type        TEXT NOT NULL,
    retry_count     INTEGER NOT NULL DEFAULT 0,
    last_error      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_attempt_at TIMESTAMPTZ,
    UNIQUE(edge_id)                                  -- 一条 edge 一行 outbox, 重试不重写
);

CREATE INDEX IF NOT EXISTS idx_pending_milvus_user
    ON pending_milvus_inserts(user_id);

-- partial index for "still pending" rows (retry_count < threshold)
CREATE INDEX IF NOT EXISTS idx_pending_milvus_active
    ON pending_milvus_inserts(created_at)
    WHERE retry_count < 5;
