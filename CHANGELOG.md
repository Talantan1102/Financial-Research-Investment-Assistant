# Changelog

All notable changes to this project will be documented in this file.

## [v0.9.0-plan3] — 2026-05-10

### Added — Escalation Channel (chat → research handoff)
- POST `/api/v0/chat/escalate` SSE endpoint streams `research_*` events + `escalate_done`
- LLM-fill `EscalationPacket` (4-class signal schema: ExplicitTask / ChatDerivedSignals / KnownFacts / SessionMetadata + MissingFieldHint)
- `EscalationExtractor` agent — chat history → packet draft via prompt
- `escalation_records` PG table (packet_draft / packet_confirmed / user_edits jsonb) — prompt-tuning trace
- `research_reports.source_chat_session_id` FK + double-write to `ChatMessage(message_type=research_report)` for bidirectional link
- `ResearchPlanner` / `Analyst` / `Writer` prompts honor chat-derived signals (entities, preferences, known tools)
- New SSE event types: `escalate_request`, `escalate_packet_draft`, `research_planner_done`, `research_analyst_done`, `research_writer_done`, `research_critic_done`, `research_tool_start`, `research_tool_end`, `escalate_done`, `escalate_error`

### Industrial problems hit (from spec § 6)
- E1 packet schema (full 4-class + sub-class definitions)
- E2 progress visibility (research_* SSE during minute-long research)
- E4 failure rollback (research crash + double-write failure both → status=failed)
- E9 LLM extraction quality (prompt + golden tests)
- E10 missing-field detect (`MissingFieldHint`)
- E11 dialog inline edit (wire format only — UI in Plan 4)
- E12 packet diff trace (`user_edits` jsonb captures LLM→user diffs)
- E13 bidirectional link (FK + ChatMessage row)
- E14 reports table compatibility (additive `source_chat_session_id` column with ON DELETE SET NULL)

## [v0.9.0-plan1] — 2026-05-09

### Added
- backend ChatAgent v0.9: LangGraph supervisor (context_node + planner_node + tool_node + responder_node)
- 6 MCP tools via stdio (get_stock_quote / get_financials / get_news / web_search / kb_search / compare_stocks)
- ToolResultCache with per-tool TTL + user_id namespace (PG-backed, async SQLAlchemy)
- AsyncPostgresSaver replaces SqliteSaver (chat_graph + research_graph)
- /api/v0/chat SSE endpoint re-wired to app_main, 19 event types + monotonic seq
- /api/v0/chats CRUD for multi-chat list (GET list / POST create / GET detail / DELETE)
- ChatSessionRepo (UUID-keyed, async, anonymous → NULL user_id pre-auth)
- InSessionMemory (Q4 E: tool dedup + token-guard summarize)
- PostgresCheckpointerConfig + make_postgres_checkpointer factory (psycopg3 async pool)
- MCPClient subprocess lifecycle managed in FastAPI lifespan

### Changed
- ResearchAgent checkpointer migrated to PG (pipeline unchanged)
- ChatState (renamed from GraphState, alias preserved) adds history / cache / escalation hooks
- ChatMessage + ChatSession ORM extended (message_type, research_report_id, research_report_summary, tool_call_data, message_count, last_msg_preview)
- app_main lifespan now initialises PG checkpointer + MCP client + ChatSessionRepo
- _async_pg_url() split: plain postgresql:// for psycopg3 pool; postgresql+psycopg:// for SQLAlchemy engine

### Fixed
- tier="default" → tier="fast" in Responder.run() and InSessionMemory.summarize()
- anonymous user_id maps to NULL FK (not nil UUID) to avoid FK violation pre-auth
- list_for_user uses IS NULL filter when user_id is None
- greenlet added as explicit dep (required by SQLAlchemy async on Python 3.13)

### Removed
- legacy SqliteSaver factory (`app/orchestration/checkpointer.py`)
- unused asyncpg dep (lcp 3.x uses psycopg3)
- db_path argument from build_chat_graph() (replaced by checkpointer kwarg)
