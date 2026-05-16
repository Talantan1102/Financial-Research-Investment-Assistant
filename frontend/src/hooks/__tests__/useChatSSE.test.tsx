import { http, HttpResponse as MswHttpResponse } from 'msw'
import { describe, expect, it, beforeEach } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { snapshot } from 'valtio'
import { useChatSSE } from '@/hooks/useChatSSE'
import { server } from '@/test-utils/msw-server'
import { sseResponse, controllableSseResponse } from '@/test-utils/sse-mock'
import {
  currentChatActions,
  currentChatState,
} from '@/store/current-chat'
import type { ChatDetail, ChatMessage, ChatSession } from '@/types/chat'

function makeSession(id: string): ChatSession {
  return {
    id,
    user_id: null,
    title: 'mock',
    created_at: '2026-05-16T00:00:00Z',
    last_active_at: '2026-05-16T00:00:00Z',
    message_count: 0,
    last_msg_preview: null,
  }
}

function makeMessage(
  id: string,
  role: ChatMessage['role'],
  content: string,
  sessionId: string,
): ChatMessage {
  return {
    id,
    session_id: sessionId,
    role,
    content,
    message_type: 'text',
    tool_call_data: null,
    research_report_id: null,
    research_report_summary: null,
    created_at: '2026-05-16T00:00:00Z',
  }
}

const API_BASE = (import.meta.env.VITE_API_BASE as string) ?? ''

describe('useChatSSE — basic consume', () => {
  beforeEach(() => {
    currentChatActions.reset()
    currentChatActions.setSession('s1', [])
  })

  it('streams events from POST /api/v0/chat into currentChatStore', async () => {
    server.use(
      http.post(`${API_BASE}/api/v0/chat`, () =>
        sseResponse([
          { type: 'token', seq: 1, content: 'Hel' },
          { type: 'token', seq: 2, content: 'lo' },
          { type: 'done', seq: 3 },
        ]),
      ),
    )

    const { result } = renderHook(() => useChatSSE({ sessionId: 's1' }))

    await act(async () => {
      await result.current.sendMessage('hi')
    })

    await waitFor(() => {
      expect(snapshot(currentChatState).last_seq).toBe(3)
    })
    expect(snapshot(currentChatState).streamingStatus).toBe('idle')
    expect(snapshot(currentChatState).messages.at(-1)?.content).toBe('Hello')
  })
})

describe('useChatSSE — abort', () => {
  beforeEach(() => {
    currentChatActions.reset()
    currentChatActions.setSession('s1', [])
  })

  it('abort() stops dispatching subsequent events', async () => {
    const ctrl = controllableSseResponse()
    server.use(
      http.post(`${API_BASE}/api/v0/chat`, () => ctrl.response),
    )

    const { result } = renderHook(() => useChatSSE({ sessionId: 's1' }))
    const send = result.current.sendMessage('hi')
    ctrl.push({ type: 'token', seq: 1, content: 'a' })
    await waitFor(() => {
      expect(snapshot(currentChatState).last_seq).toBe(1)
    })
    act(() => result.current.abort())
    ctrl.push({ type: 'token', seq: 2, content: 'b' })
    ctrl.disconnect()
    await send.catch(() => {})
    expect(snapshot(currentChatState).last_seq).toBe(1)
  })
})

describe('useChatSSE — Plan 1: 断流后改一次性 history reload', () => {
  beforeEach(() => {
    currentChatActions.reset()
    currentChatActions.setSession('s1', [])
  })

  it('calls GET /api/v0/chats/:id (not /chat/stream/:id) when initial stream closes early', async () => {
    let initialSeen = false
    let getChatSeen = false
    let legacyStreamSeen = false

    server.use(
      http.post(`${API_BASE}/api/v0/chat`, () => {
        initialSeen = true
        return sseResponse([
          { type: 'token', seq: 1, content: 'A' },
          { type: 'token', seq: 2, content: 'B' },
        ])
      }),
      http.get(`${API_BASE}/api/v0/chats/s1`, () => {
        getChatSeen = true
        const detail: ChatDetail = {
          session: makeSession('s1'),
          messages: [
            makeMessage('m-user', 'user', 'hi', 's1'),
            makeMessage('m-asst', 'assistant', 'AB (persisted)', 's1'),
          ],
        }
        return MswHttpResponse.json(detail)
      }),
      http.get(`${API_BASE}/api/v0/chat/stream/s1`, () => {
        // Legacy endpoint must NOT be hit anymore.
        legacyStreamSeen = true
        return new MswHttpResponse(null, { status: 404 })
      }),
    )

    const { result } = renderHook(() =>
      useChatSSE({ sessionId: 's1', delayMs: async () => {} }),
    )
    await act(async () => {
      await result.current.sendMessage('hi')
    })

    expect(initialSeen).toBe(true)
    expect(getChatSeen).toBe(true)
    expect(legacyStreamSeen).toBe(false)
  })

  it('replaces currentChatState.messages with the GET /chats/:id response', async () => {
    server.use(
      http.post(`${API_BASE}/api/v0/chat`, () =>
        sseResponse([
          { type: 'token', seq: 1, content: 'A' },
          { type: 'token', seq: 2, content: 'B' },
        ]),
      ),
      http.get(`${API_BASE}/api/v0/chats/s1`, () => {
        const detail: ChatDetail = {
          session: makeSession('s1'),
          messages: [
            makeMessage('m-user', 'user', 'hi', 's1'),
            makeMessage('m-asst', 'assistant', 'reloaded AB content', 's1'),
          ],
        }
        return MswHttpResponse.json(detail)
      }),
    )

    const { result } = renderHook(() =>
      useChatSSE({ sessionId: 's1', delayMs: async () => {} }),
    )
    await act(async () => {
      await result.current.sendMessage('hi')
    })

    const s = snapshot(currentChatState)
    // After reload via setSession, messages should match the GET response.
    expect(s.messages.length).toBe(2)
    expect(s.messages.at(-1)?.content).toBe('reloaded AB content')
    expect(s.messages.at(-1)?.role).toBe('assistant')
    expect(s.last_seq).toBe(0) // setSession resets last_seq
    expect(s.streamingDraft).toBe('')
  })

  it('does not throw and leaves status untouched if GET /chats/:id fails', async () => {
    server.use(
      http.post(`${API_BASE}/api/v0/chat`, () =>
        sseResponse([{ type: 'token', seq: 1, content: 'A' }]),
      ),
      http.get(`${API_BASE}/api/v0/chats/s1`, () =>
        new MswHttpResponse(null, { status: 500 }),
      ),
    )

    const { result } = renderHook(() =>
      useChatSSE({ sessionId: 's1', delayMs: async () => {} }),
    )
    await act(async () => {
      await result.current.sendMessage('hi')
    })
    // Silent failure — should not loop / throw; reconnecting status persists.
    expect(snapshot(currentChatState).streamingStatus).toBe('reconnecting')
  })
})

describe('useChatSSE — F8 multi-chat lifecycle', () => {
  beforeEach(() => currentChatActions.reset())

  it('aborts old stream when sessionId changes (F8)', async () => {
    const ctrlA = controllableSseResponse()
    server.use(
      http.post(`${API_BASE}/api/v0/chat`, () => ctrlA.response),
    )

    const { result, rerender } = renderHook(
      ({ sid }: { sid: string }) =>
        useChatSSE({ sessionId: sid, delayMs: async () => {} }),
      { initialProps: { sid: 'A' } },
    )
    currentChatActions.setSession('A', [])
    const send = result.current.sendMessage('hello')
    ctrlA.push({ type: 'token', seq: 1, content: 'fromA' })
    await waitFor(() => {
      expect(snapshot(currentChatState).last_seq).toBe(1)
    })

    currentChatActions.setSession('B', [])
    rerender({ sid: 'B' })

    ctrlA.push({ type: 'token', seq: 2, content: 'fromA-late' })
    ctrlA.disconnect()
    await send.catch(() => {})

    const s = snapshot(currentChatState)
    expect(s.session_id).toBe('B')
    expect(s.last_seq).toBe(0)
  })
})
