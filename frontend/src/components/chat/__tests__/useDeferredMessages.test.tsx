import { act, renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { useDeferredMessages } from '@/components/chat/useDeferredMessages'
import type { ChatMessage } from '@/types/chat'

function m(id: string, content: string): ChatMessage {
  return {
    id,
    session_id: 's',
    role: 'assistant',
    content,
    message_type: 'text',
    tool_call_data: null,
    research_report_id: null,
    research_report_summary: null,
    created_at: '2026-05-09T00:00:00Z',
  }
}

describe('useDeferredMessages', () => {
  it('returns deferred snapshot of messages array', () => {
    const initial = [m('a', 'x')]
    const { result, rerender } = renderHook(
      ({ msgs }: { msgs: readonly ChatMessage[] }) => useDeferredMessages(msgs),
      { initialProps: { msgs: initial as readonly ChatMessage[] } },
    )
    expect(result.current).toEqual(initial)
    const updated = [m('a', 'x'), m('b', 'y')]
    act(() => rerender({ msgs: updated as readonly ChatMessage[] }))
    expect(result.current.length).toBe(2)
  })
})
