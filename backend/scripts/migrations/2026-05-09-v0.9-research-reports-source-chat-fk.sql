-- Add source_chat_session_id FK to research_reports for chat→research escalation trace.
-- Idempotent: safe to re-run. ON DELETE SET NULL preserves report when chat deleted (E14).

ALTER TABLE research_reports
  ADD COLUMN IF NOT EXISTS source_chat_session_id UUID;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'fk_research_reports_source_chat_session'
  ) THEN
    ALTER TABLE research_reports
      ADD CONSTRAINT fk_research_reports_source_chat_session
      FOREIGN KEY (source_chat_session_id)
      REFERENCES chat_sessions(id)
      ON DELETE SET NULL;
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_research_reports_source_chat_session
  ON research_reports (source_chat_session_id);
