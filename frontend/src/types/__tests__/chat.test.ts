import { describe, expect, expectTypeOf, it } from 'vitest'
import type {
  ChatMessage,
  ChatSession,
  SSEEvent,
  TokenEvent,
} from '@/types/chat'

describe('SSE event types', () => {
  it('SSEEvent is a discriminated union over `type`', () => {
    const ev: SSEEvent = { type: 'token', seq: 1, content: 'hi' }
    expectTypeOf(ev).toMatchTypeOf<TokenEvent>()
  })

  it('all 19 event variants are constructible with seq field', () => {
    const samples: SSEEvent[] = [
      { type: 'token', seq: 1, content: 'x' },
      { type: 'plan', seq: 2, plan: { steps: [] } },
      { type: 'tool_start', seq: 3, tool_name: 't', tool_args: {}, call_id: 'c1' },
      { type: 'tool_end', seq: 4, call_id: 'c1', result: {} },
      { type: 'tool_error', seq: 5, call_id: 'c1', error: 'oops' },
      { type: 'skill_load', seq: 6, skill_name: 's', level: 'L2' },
      { type: 'escalate_request', seq: 7, reason: 'ambiguous' },
      {
        type: 'escalate_packet_draft',
        seq: 8,
        packet: {
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
        },
      },
      { type: 'research_planner_done', seq: 9, plan: {} },
      { type: 'research_tool_start', seq: 10, tool_name: 't', tool_args: {}, call_id: 'c2' },
      { type: 'research_tool_end', seq: 11, call_id: 'c2', result: {} },
      { type: 'research_analyst_done', seq: 12, summary: '' },
      { type: 'research_writer_done', seq: 13, draft_summary: '' },
      { type: 'research_critic_done', seq: 14, score: 0 },
      { type: 'escalate_done', seq: 15, research_report_id: 'r1' },
      { type: 'escalate_error', seq: 16, error: 'failed' },
      { type: 'cost_update', seq: 17, cost_so_far: 0.01, tokens: { prompt: 10, completion: 5 } },
      { type: 'done', seq: 18 },
      { type: 'error', seq: 19, error: 'fatal' },
    ]
    expect(samples).toHaveLength(19)
  })

  it('ChatSession + ChatMessage shapes match backend DTOs', () => {
    const s: ChatSession = {
      id: 's1',
      user_id: null,
      title: 't',
      created_at: '2026-05-09T00:00:00Z',
      last_active_at: '2026-05-09T00:00:00Z',
      message_count: 0,
      last_msg_preview: null,
    }
    const m: ChatMessage = {
      id: 'm1',
      session_id: 's1',
      role: 'user',
      content: 'hi',
      message_type: 'text',
      tool_call_data: null,
      research_report_id: null,
      research_report_summary: null,
      created_at: '2026-05-09T00:00:00Z',
    }
    expectTypeOf(s).toMatchTypeOf<ChatSession>()
    expectTypeOf(m).toMatchTypeOf<ChatMessage>()
  })
})
