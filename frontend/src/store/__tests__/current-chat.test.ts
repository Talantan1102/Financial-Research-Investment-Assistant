import { describe, expect, it, beforeEach } from 'vitest'
import { snapshot } from 'valtio'
import {
  currentChatActions,
  currentChatState,
} from '@/store/current-chat'
import type { SSEEvent } from '@/types/chat'

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

  it('dispatchEvent: cost_update updates cost_so_far', () => {
    currentChatActions.setSession('s1', [])
    currentChatActions.dispatchEvent({
      type: 'cost_update',
      seq: 5,
      cost_so_far: 0.0042,
      tokens: { prompt: 100, completion: 50 },
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
