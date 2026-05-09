/**
 * frontend/src/types/escalation.ts
 *
 * EscalationPacket schema mirrored from spec § 4.4 (cbc13d0).
 * Field names stay snake_case (wire format).
 */

export interface EscalationPacket {
  explicit_task: ExplicitTask
  chat_derived_signals: ChatDerivedSignals
  known_facts: KnownFacts
  session_metadata: SessionMetadata
  missing_field_hints: MissingFieldHint[]
}

export interface ExplicitTask {
  raw_last_user_turn: string
  extracted_intent: string
  target_ts_code: string | null
  target_entity_name: string | null
  user_extra_message: string | null
}

export interface ChatDerivedSignals {
  entities: Entity[]
  preferences: Preference[]
  open_questions: string[]
  inferred_persona: string | null
  extraction_confidence: number
}

export interface Entity {
  name: string
  ts_code: string | null
  role: 'primary_target' | 'comparative_target' | 'mentioned_in_passing'
  mention_turn_indices: number[]
}

export interface Preference {
  text: string
  category: 'risk_tolerance' | 'focus_metric' | 'comparative_focus' | 'horizon' | 'other'
  confidence: number
}

export interface KnownFacts {
  tool_results: ToolResultRef[]
}

export interface ToolResultRef {
  tool_name: string
  tool_args: Record<string, unknown>
  result_summary: string
  cached_at: string
  cache_id: string
}

export interface SessionMetadata {
  chat_session_id: string
  chat_turn_count: number
  chat_history_summary: string | null
  user_confirmed_at: string
  user_edits: FieldEdit[]
}

export interface FieldEdit {
  field_path: string
  llm_value: unknown
  user_value: unknown
  edit_type: 'modify' | 'delete' | 'add'
}

export interface MissingFieldHint {
  field_path: string
  reason: 'llm_uncertain' | 'schema_required_but_empty' | 'user_skipped'
  llm_question_for_user: string
}

export interface ResearchProgress {
  stage:
    | 'idle'
    | 'planner_running'
    | 'tool_running'
    | 'analyst_running'
    | 'writer_running'
    | 'critic_running'
    | 'done'
    | 'error'
  message?: string
  research_report_id?: string
}
