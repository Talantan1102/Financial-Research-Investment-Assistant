-- C.5 Plan 5: posterior calibration weekly job audit table.
-- spec § 11 末尾 #3: importance 行为信号反向校准 — YouTube/TikTok prediction + posterior calibration.
-- 每次 weekly job 一行, scanned/promoted/demoted/overridden 计数.

CREATE TABLE IF NOT EXISTS chat_memory_calibration_runs (
    run_id              UUID PRIMARY KEY,
    started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at         TIMESTAMPTZ,
    scanned_edges       INTEGER NOT NULL DEFAULT 0,
    promoted_to_high    INTEGER NOT NULL DEFAULT 0,
    demoted_to_medium   INTEGER NOT NULL DEFAULT 0,
    overridden_to_low   INTEGER NOT NULL DEFAULT 0,
    status              VARCHAR(32) NOT NULL DEFAULT 'running',
    error_message       TEXT
);

CREATE INDEX IF NOT EXISTS idx_calibration_runs_started_at
    ON chat_memory_calibration_runs (started_at DESC);
