-- LangGraph 1.x AsyncPostgresSaver state persistence schema.
-- AsyncPostgresSaver.setup() creates required tables on first run, but we
-- provide explicit schema isolation here so business tables (in 'public')
-- and LangGraph state are clearly namespaced.
--
-- Idempotent: safe to run multiple times.

CREATE SCHEMA IF NOT EXISTS langgraph_checkpoints;

-- Grant usage to the application role (assumes default 'postgres' user; adjust
-- if multi-role setup is added in a later milestone).
GRANT USAGE ON SCHEMA langgraph_checkpoints TO postgres;
GRANT CREATE ON SCHEMA langgraph_checkpoints TO postgres;
