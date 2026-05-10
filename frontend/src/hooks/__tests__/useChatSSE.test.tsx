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

describe('useChatSSE — F6 backoff sequence', () => {
  beforeEach(() => {
    currentChatActions.reset()
    currentChatActions.setSession('s1', [])
  })

  it('uses 1s/2s/4s delays before successful reconnect', async () => {
    const delays: number[] = []
    let callCount = 0
    server.use(
      http.post(`${API_BASE}/api/v0/chat`, () =>
        sseResponse([{ type: 'token', seq: 1, content: 'A' }]),
      ),
      http.get(`${API_BASE}/api/v0/chat/stream/s1`, () => {
        callCount += 1
        if (callCount < 3) return new MswHttpResponse(null, { status: 503 })
        return sseResponse([{ type: 'done', seq: 2 }])
      }),
    )
    const { result } = renderHook(() =>
      useChatSSE({
        sessionId: 's1',
        delayMs: async (ms) => {
          delays.push(ms)
        },
      }),
    )
    await act(async () => {
      await result.current.sendMessage('hi')
    })
    expect(delays.slice(0, 3)).toEqual([1000, 2000, 4000])
    expect(snapshot(currentChatState).last_seq).toBe(2)
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
