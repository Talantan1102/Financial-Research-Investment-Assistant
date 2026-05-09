import { describe, expect, it, beforeEach } from 'vitest'
import { snapshot } from 'valtio'
import { escalationActions, escalationState } from '@/store/escalation'
import type { EscalationPacket, FieldEdit } from '@/types/escalation'

const emptyPacket: EscalationPacket = {
  explicit_task: {
    raw_last_user_turn: 'compare ICBC and CMB',
    extracted_intent: 'comparative_research',
    target_ts_code: '601398.SH',
    target_entity_name: 'ICBC',
    user_extra_message: null,
  },
  chat_derived_signals: {
    entities: [],
    preferences: [],
    open_questions: [],
    inferred_persona: null,
    extraction_confidence: 0.6,
  },
  known_facts: { tool_results: [] },
  session_metadata: {
    chat_session_id: 's1',
    chat_turn_count: 4,
    chat_history_summary: null,
    user_confirmed_at: '',
    user_edits: [],
  },
  missing_field_hints: [],
}

describe('escalationStore', () => {
  beforeEach(() => escalationActions.reset())

  it('starts in idle phase with no draft', () => {
    const s = snapshot(escalationState)
    expect(s.phase).toBe('idle')
    expect(s.packet_draft).toBeNull()
  })

  it('setPacketDraft transitions to draft phase', () => {
    escalationActions.setPacketDraft(emptyPacket)
    const s = snapshot(escalationState)
    expect(s.phase).toBe('draft')
    expect(s.packet_draft?.explicit_task.target_ts_code).toBe('601398.SH')
  })

  it('recordEdit appends to user_edits', () => {
    escalationActions.setPacketDraft(emptyPacket)
    const edit: FieldEdit = {
      field_path: 'explicit_task.target_ts_code',
      llm_value: '601398.SH',
      user_value: '600036.SH',
      edit_type: 'modify',
    }
    escalationActions.recordEdit(edit)
    const s = snapshot(escalationState)
    expect(s.user_edits).toHaveLength(1)
  })

  it('setResearchProgress updates research_progress', () => {
    escalationActions.setResearchProgress({
      stage: 'planner_running',
      message: 'plan generated',
    })
    const s = snapshot(escalationState)
    expect(s.research_progress.stage).toBe('planner_running')
  })

  it('confirm sets phase=confirmed', () => {
    escalationActions.setPacketDraft(emptyPacket)
    escalationActions.confirm()
    expect(snapshot(escalationState).phase).toBe('confirmed')
  })
})
