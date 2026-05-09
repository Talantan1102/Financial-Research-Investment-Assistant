import { describe, expectTypeOf, it } from 'vitest'
import type {
  Entity,
  EscalationPacket,
  FieldEdit,
} from '@/types/escalation'

describe('EscalationPacket types', () => {
  it('EscalationPacket has 5 top-level fields', () => {
    const p: EscalationPacket = {
      explicit_task: {
        raw_last_user_turn: '',
        extracted_intent: '',
        target_ts_code: null,
        target_entity_name: null,
        user_extra_message: null,
      },
      chat_derived_signals: {
        entities: [],
        preferences: [],
        open_questions: [],
        inferred_persona: null,
        extraction_confidence: 0,
      },
      known_facts: { tool_results: [] },
      session_metadata: {
        chat_session_id: 's1',
        chat_turn_count: 0,
        chat_history_summary: null,
        user_confirmed_at: '2026-05-09T00:00:00Z',
        user_edits: [],
      },
      missing_field_hints: [],
    }
    expectTypeOf(p).toMatchTypeOf<EscalationPacket>()
  })

  it('Entity role is union of 3 literals', () => {
    const e: Entity = {
      name: 'ICBC',
      ts_code: '601398.SH',
      role: 'primary_target',
      mention_turn_indices: [1, 3],
    }
    expectTypeOf(e).toMatchTypeOf<Entity>()
  })

  it('FieldEdit edit_type is union of 3 literals', () => {
    const f: FieldEdit = {
      field_path: 'explicit_task.target_ts_code',
      llm_value: '600000.SH',
      user_value: '601398.SH',
      edit_type: 'modify',
    }
    expectTypeOf(f).toMatchTypeOf<FieldEdit>()
  })
})
