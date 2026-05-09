import { http } from 'msw'
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

describe('useChatSSE — F6 reconnect (last_event_id)', () => {
  beforeEach(() => {
    currentChatActions.reset()
    currentChatActions.setSession('s1', [])
  })

  it('reconnects to /stream/:id?last_event_id=N when initial stream closes early', async () => {
    let initialSeen = false
    let reconnectQuery: string | null = null

    server.use(
      http.post(`${API_BASE}/api/v0/chat`, () => {
        initialSeen = true
        return sseResponse([
          { type: 'token', seq: 1, content: 'A' },
          { type: 'token', seq: 2, content: 'B' },
        ])
      }),
      http.get(`${API_BASE}/api/v0/chat/stream/s1`, ({ request }) => {
        reconnectQuery = new URL(request.url).searchParams.get('last_event_id')
        return sseResponse([
          { type: 'token', seq: 3, content: 'C' },
          { type: 'done', seq: 4 },
        ])
      }),
    )

    const { result } = renderHook(() =>
      useChatSSE({ sessionId: 's1', delayMs: async () => {} }),
    )
    await act(async () => {
      await result.current.sendMessage('hi')
    })
    expect(initialSeen).toBe(true)
    expect(reconnectQuery).toBe('2')
    expect(snapshot(currentChatState).last_seq).toBe(4)
    expect(snapshot(currentChatState).streamingDraft).toBe('')
    expect(snapshot(currentChatState).messages.at(-1)?.content).toBe('ABC')
    expect(snapshot(currentChatState).streamingStatus).toBe('idle')
  })
})
