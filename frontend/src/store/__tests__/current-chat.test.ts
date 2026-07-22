import { describe, expect, it, beforeEach } from 'vitest'
import { snapshot } from 'valtio'
import {
  currentChatActions,
  currentChatState,
} from '@/store/current-chat'
import type { SSEEvent } from '@/types/chat'
import { paperTradingState } from '@/store/paper-trading'

describe('currentChatStore', () => {
  beforeEach(() => currentChatActions.reset())

  it('starts empty', () => {
    const s = snapshot(currentChatState)
    expect(s.session_id).toBeNull()
    expect(s.messages).toEqual([])
    expect(s.streamingStatus).toBe('idle')
    expect(s.last_seq).toBe(0)
    expect(s.cost_so_far).toBe(0)
  })

  it('setSession resets dispatch state but loads messages', () => {
    currentChatActions.setSession('s1', [
      {
        id: 'm1',
        session_id: 's1',
        role: 'user',
        content: 'hello',
        message_type: 'text',
        tool_call_data: null,
        research_report_id: null,
        research_report_summary: null,
        created_at: '2026-05-09T00:00:00Z',
      },
    ])
    const s = snapshot(currentChatState)
    expect(s.session_id).toBe('s1')
    expect(s.messages).toHaveLength(1)
  })

  it('setSession restores paper approval cards from persisted messages', () => {
    currentChatActions.setSession('s1', [
      {
        id: 'approval-message',
        session_id: 's1',
        role: 'assistant',
        content: '',
        message_type: 'paper_approval',
        tool_call_data: {
          approval_id: 'approval-a1',
          approval_type: 'paper_order',
          resource_id: 'o1',
          proposal: {
            side: 'buy',
            ts_code: '600000.SH',
            name: '浦发银行',
            quantity: 100,
            order_type: 'limit',
            limit_price: '10.00',
          },
          preview: {
            order_id: 'o1',
            draft: {
              side: 'buy',
              ts_code: '600000.SH',
              name: '浦发银行',
              quantity: 100,
              order_type: 'limit',
              limit_price: '10.00',
            },
            quote: { price: '10.00' },
            estimated_gross: '1000',
            estimated_fees: {},
            estimated_cash_required: '1000',
            available_cash: '10000',
            sellable_quantity: 0,
            market_phase: 'open',
            rules_version: 'v1',
          },
          expires_at: '2026-07-22T10:00:00Z',
        },
        research_report_id: null,
        research_report_summary: null,
        created_at: '2026-07-22T00:00:00Z',
      },
    ])
    expect(paperTradingState.approvals['approval-a1'].resource_id).toBe('o1')
    expect(paperTradingState.approvals['approval-a1'].phase).toBe('preview')
  })

  it('dispatchEvent: token appends streaming-content + advances last_seq', () => {
    currentChatActions.setSession('s1', [])
    currentChatActions.beginStreaming()
    const ev: SSEEvent = { type: 'token', seq: 1, content: 'Hel' }
    currentChatActions.dispatchEvent(ev)
    currentChatActions.dispatchEvent({ type: 'token', seq: 2, content: 'lo' })
    const s = snapshot(currentChatState)
    expect(s.last_seq).toBe(2)
    expect(s.streamingDraft).toBe('Hello')
  })

  it('dispatchEvent: cost_update updates cost_so_far from cny (chatloop shape)', () => {
    currentChatActions.setSession('s1', [])
    currentChatActions.dispatchEvent({
      type: 'cost_update',
      seq: 5,
      cny: 0.0042,
      tokens: 150,
      cached_tokens: 30,
    })
    const s = snapshot(currentChatState)
    expect(s.cost_so_far).toBeCloseTo(0.0042)
  })

  it('dispatchEvent: ignores out-of-order events with seq <= last_seq (G1)', () => {
    currentChatActions.setSession('s1', [])
    currentChatActions.dispatchEvent({ type: 'token', seq: 5, content: 'a' })
    currentChatActions.dispatchEvent({ type: 'token', seq: 3, content: 'b' })
    const s = snapshot(currentChatState)
    expect(s.streamingDraft).toBe('a')
    expect(s.last_seq).toBe(5)
  })

  it('dispatchEvent returns false for an out-of-order event', () => {
    currentChatActions.setSession('s1', [])
    expect(currentChatActions.dispatchEvent({ type: 'token', seq: 5, content: 'a' })).toBe(true)
    expect(currentChatActions.dispatchEvent({ type: 'token', seq: 3, content: 'b' })).toBe(false)
  })

  it('dispatchEvent: done flushes streamingDraft into a message + sets idle', () => {
    currentChatActions.setSession('s1', [])
    currentChatActions.beginStreaming()
    currentChatActions.dispatchEvent({ type: 'token', seq: 1, content: 'Hi' })
    currentChatActions.dispatchEvent({ type: 'done', seq: 2 })
    const s = snapshot(currentChatState)
    expect(s.streamingStatus).toBe('idle')
    expect(s.streamingDraft).toBe('')
    expect(s.messages.at(-1)?.content).toBe('Hi')
  })

  it('dispatchEvent: error sets streamingStatus=error', () => {
    currentChatActions.setSession('s1', [])
    currentChatActions.beginStreaming()
    currentChatActions.dispatchEvent({
      type: 'error',
      seq: 1,
      error: 'oops',
    })
    expect(snapshot(currentChatState).streamingStatus).toBe('error')
  })

  // C32: beginStreaming must reset last_seq so 2nd+ messages don't dedup their events
  it('C32: beginStreaming resets last_seq — second message in session receives all events', () => {
    currentChatActions.setSession('s1', [])

    // First message: drive seq 1-3
    currentChatActions.beginStreaming()
    currentChatActions.dispatchEvent({ type: 'token', seq: 1, content: 'A' })
    currentChatActions.dispatchEvent({ type: 'token', seq: 2, content: 'B' })
    currentChatActions.dispatchEvent({ type: 'token', seq: 3, content: 'C' })
    currentChatActions.dispatchEvent({ type: 'done', seq: 4 })
    expect(snapshot(currentChatState).last_seq).toBe(4)

    // Second message: beginStreaming must reset last_seq to 0
    currentChatActions.beginStreaming()
    expect(snapshot(currentChatState).last_seq).toBe(0)

    // seq 1-3 again — must NOT be deduped
    currentChatActions.dispatchEvent({ type: 'token', seq: 1, content: 'X' })
    currentChatActions.dispatchEvent({ type: 'token', seq: 2, content: 'Y' })
    currentChatActions.dispatchEvent({ type: 'token', seq: 3, content: 'Z' })
    currentChatActions.dispatchEvent({ type: 'done', seq: 4 })

    const s = snapshot(currentChatState)
    // streamingStatus back to idle after done
    expect(s.streamingStatus).toBe('idle')
    // The second message's draft was flushed into messages
    expect(s.messages.at(-1)?.content).toBe('XYZ')
  })
})

// Phase 5 Task 5.1: chatloop new event branches in dispatchEvent.
describe('dispatchEvent — chatloop new events', () => {
  beforeEach(() => {
    currentChatActions.reset()
    currentChatActions.setSession('s1', [])
    currentChatActions.beginStreaming()
  })

  it('step_start sets loop_progress + thinking phase', () => {
    currentChatActions.dispatchEvent({ type: 'step_start', seq: 1, step: 2, max_steps: 12 })
    const s = snapshot(currentChatState)
    expect(s.loop_progress).toEqual({ step: 2, max_steps: 12 })
    expect(s.streaming_phase).toBe('thinking')
  })

  it('tool_call (hub shape {tool,args}) → tool phase + enters toolEvents', () => {
    currentChatActions.dispatchEvent({ type: 'tool_call', seq: 1, tool: 'get_stock_quote', args: { ts_code: '601398.SH' } })
    const s = snapshot(currentChatState)
    expect(s.streaming_phase).toBe('tool')
    expect(s.toolEvents.at(-1)?.type).toBe('tool_call')
  })

  it('tool_start → tool phase', () => {
    currentChatActions.dispatchEvent({ type: 'tool_start', seq: 1, tool: 'get_stock_quote' })
    expect(snapshot(currentChatState).streaming_phase).toBe('tool')
  })

  it('token sets writing phase', () => {
    currentChatActions.dispatchEvent({ type: 'token', seq: 1, content: 'hi' })
    expect(snapshot(currentChatState).streaming_phase).toBe('writing')
  })

  it('tool_error enters toolEvents (carries error + hint)', () => {
    currentChatActions.dispatchEvent({ type: 'tool_error', seq: 1, tool: 't', error: 'rate limit', hint: '稍后再试' })
    const last = snapshot(currentChatState).toolEvents.at(-1)
    expect(last?.type).toBe('tool_error')
  })

  it('steer_merged enters toolEvents (preview)', () => {
    currentChatActions.dispatchEvent({ type: 'steer_merged', seq: 1, preview: '看一下营收' })
    const last = snapshot(currentChatState).toolEvents.at(-1)
    expect(last?.type).toBe('steer_merged')
  })

  it('loop_halt stores halt_reason', () => {
    currentChatActions.dispatchEvent({ type: 'loop_halt', seq: 1, reason: 'max_steps' })
    expect(snapshot(currentChatState).halt_reason).toBe('max_steps')
  })

  it('done with non-natural stop_reason keeps halt_reason banner', () => {
    currentChatActions.dispatchEvent({ type: 'token', seq: 1, content: 'partial answer' })
    currentChatActions.dispatchEvent({ type: 'done', seq: 2, stop_reason: 'budget' })
    const s = snapshot(currentChatState)
    expect(s.streamingStatus).toBe('idle')
    expect(s.halt_reason).toBe('budget')
    expect(s.loop_progress).toBeNull()
  })

  it('done with natural stop_reason clears halt_reason', () => {
    currentChatActions.dispatchEvent({ type: 'loop_halt', seq: 1, reason: 'spinning' })
    currentChatActions.dispatchEvent({ type: 'done', seq: 2, stop_reason: 'natural' })
    expect(snapshot(currentChatState).halt_reason).toBeNull()
  })

  it('done with stop_reason absent preserves existing halt_reason (loop_halt banner guard)', () => {
    // loop_halt sets halt_reason; a bare done event (no stop_reason field) must
    // NOT erase it — the banner should stay visible after the turn ends.
    currentChatActions.dispatchEvent({ type: 'loop_halt', seq: 1, reason: 'max_steps' })
    currentChatActions.dispatchEvent({ type: 'done', seq: 2 }) // no stop_reason
    expect(snapshot(currentChatState).halt_reason).toBe('max_steps')
  })

  it('out-of-order new events with seq <= last_seq are dropped (G1)', () => {
    currentChatActions.dispatchEvent({ type: 'step_start', seq: 5, step: 1, max_steps: 12 })
    // stale step_start (seq 3 <= 5) must NOT overwrite loop_progress
    currentChatActions.dispatchEvent({ type: 'step_start', seq: 3, step: 99, max_steps: 99 })
    const s = snapshot(currentChatState)
    expect(s.last_seq).toBe(5)
    expect(s.loop_progress).toEqual({ step: 1, max_steps: 12 })
  })
})
