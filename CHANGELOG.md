# Changelog

All notable changes to this project will be documented in this file.

## [v0.9.0] — 2026-05-10

### Added — v0.9 chat mode (C.1 + C.2 production-style)

**Backend:**
- ChatAgent v0.9 — LangGraph supervisor (context_node → planner → tool/responder)
- 6 MCP tool wrappers via stdio: get_stock_quote / get_financials / get_news / web_search / kb_search / compare_stocks
- ToolResultCache (per-tool TTL + user_id namespace)
- AsyncPostgresSaver — LangGraph state 全切 PG schema=langgraph_checkpoints
- ChatSessionRepo + multi-chat REST CRUD (`/api/v0/chats`, `/api/v0/chat`, SSE)
- Skill L1/L2/L3 progressive disclosure loader + sandboxed L3b script executor (subprocess + RLIMIT + AST safety scan + cwd isolation)
- 2 demo skills: risk_assessment (resources/) + financial_analysis (scripts/calculate_dcf.py)
- EscalationProtocol — 4-class signal packet (ExplicitTask / ChatDerivedSignals / KnownFacts / SessionMetadata) + MissingFieldHint
- POST /api/v0/chat/escalate SSE endpoint with research_* progress streaming
- ResearchState +4 chat-derived fields (chat_extracted_entities / chat_extracted_preferences / chat_known_tool_results / chat_session_id)
- ResearchPlanner / Analyst / Writer prompts honor chat-derived signals
- escalation_records PG table (packet_draft / packet_confirmed / user_edits jsonb) for prompt-tuning trace
- research_reports.source_chat_session_id FK + double-write to ChatMessage(message_type=research_report)

**Frontend (Plan 4a + 4b):**
- AppShell layout (TopBar 56px + Sidebar 240px + Main)
- Chat-first routes: `/` → /chat, /chat, /chat/:session_id, /reports
- 3 valtio stores (chatSessionsStore / currentChatStore / escalationStore)
- useChatSSE hook with last_event_id reconnect (1s/2s/4s/8s/30s cap) + multi-chat abort-on-swap
- ChatPane sub-components: MessageList (react-window virtualized) / TextMessage (marked + highlight.js + KaTeX + chart_specs) / ToolCallCard (tri-state) / ResearchReportCard / StreamingIndicator / InputArea (Enter/Shift+Enter/Cmd+K abort/⚡ Escalate) / CostMeter
- EscalationConfirmDialog: 4 sub-forms + InlineEditField + MissingFieldBanner + Confirm POST /chat/escalate
- ReportsListPage full impl + detail modal + chat deep link

**Eval / Testing:**
- 5 differential golden chat cases (short / medium / skill / escalation / multi-chat)
- E9 LLM extraction quality eval pipeline (`extraction_quality_eval.py`) using EscalationRecord.user_edits as ground truth — 5 metrics (field_accuracy / entity_recall / entity_precision / preference_F1 / missing_field_quality)
- 12 metric-function L0 smoke tests

**Industrial problems hit (30 from spec § 5):**
- A1-A4 tool selection / parallel / arg fidelity / hallucination
- B1-B3 token bloat / relevance / staleness
- C1-C2 multi-turn coordination / failure recovery
- M1-M4 MCP lifecycle / transport / schema / latency
- S1-S10 Skill progressive disclosure
- E1-E14 Escalation channel
- F1-F10 frontend polish (F10 paste-image deferred to C.4)
- G1-G10 cross-cutting

### Deferred / not done in autonomous pipeline (manual follow-up)

- 5 L2 cassettes (T2-T6) — autonomous can't safely hit real DashScope LLM
- Playwright e2e (chat-basic + chat-escalate) — needs browser install + Vite dev server
- 2 dogfood reports — manual user flows
- Judge integration over cassettes (T8) — depends on cassettes

### Deps added
- backend: langgraph-checkpoint-postgres, mcp, anthropic-skills (all in optional extras)
- frontend: msw / react-window / highlight.js / katex / react-katex / @types/react-window

## [v0.9.0-plan4b] — 2026-05-10

### Added — ChatPane + EscalationConfirmDialog + Reports + F1-F10 polish

- ChatPane sub-components: MessageList (react-window virtualized) / TextMessage (marked + hljs + KaTeX + chart_specs) / ToolCallCard (tri-state collapsed/expanded/error) / ResearchReportCard (summary + 3 actions) / StreamingIndicator (phase bar) / InputArea (4-channel UX) / CostMeter (cross-mode breakdown)
- EscalationConfirmDialog: 4 sub-forms (ExplicitTask / ChatDerivedSignals / KnownFacts / SessionMetadata) + InlineEditField + MissingFieldBanner + POST /chat/escalate Confirm flow
- ReportsListPage full impl: list + detail modal + chat deep link (E13/E14)

### F1-F10 industry polish landed
- F1 token render perf (virtualized + useDeferredValue + React.memo)
- F2 tool 卡片 tri-state with auto-expand on error + 重试 button
- F3 scroll auto-stick via IntersectionObserver
- F4 input UX (auto-resize + Enter/Shift+Enter + Cmd+K abort + ⚡ Escalate)
- F5 EscalationConfirmDialog inline structured edit + LLM 反问
- F7 markdown + KaTeX + chart_specs (3 channels)
- F9 cost meter cross-mode + StreamingIndicator phase
- F10 long prompt counter + paste image guard (upload deferred to C.4)
- F6 + F8 from Plan 4a (SSE reconnect + multi-chat lifecycle)

### Deps added
- react-window ^1.8.10 / highlight.js ^11 / katex ^0.16 / react-katex ^3 / @types/react-window
- echarts-for-react ^3 + echarts ^5 (already present)
- msw ^2.7 (Plan 4a baseline)

### Deferred to manual verification
- Playwright e2e (chat-basic + chat-escalate) — autonomous pipeline skip; can be added in a follow-up commit when browsers are installed locally

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
