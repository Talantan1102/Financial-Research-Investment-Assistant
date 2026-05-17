import { http, HttpResponse as MswHttpResponse } from 'msw'
import { describe, expect, it, beforeEach, afterEach, vi } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { snapshot } from 'valtio'
import { useChatSSE } from '@/hooks/useChatSSE'
import { server } from '@/test-utils/msw-server'
import { sseResponse, controllableSseResponse } from '@/test-utils/sse-mock'
import {
  currentChatActions,
  currentChatState,
} from '@/store/current-chat'
import * as chatSessionsStore from '@/store/chat-sessions'
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

// Default handler: the new loadSessions() calls (immediate + delayed) after SSE done
// will fire GET /api/v0/chats. Return [] to prevent MSW unhandled-request errors
// in tests that don't care about the sidebar refetch behavior.
beforeEach(() => {
  server.use(
    http.get(`${API_BASE}/api/v0/chats`, () => MswHttpResponse.json([])),
  )
})

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

describe('useChatSSE — Plan 2 双阶段(JSON → GET stream)', () => {
  beforeEach(() => {
    currentChatActions.reset()
    currentChatActions.setSession('s1', [])
  })

  it('POST 返回 JSON {task_id, stream_url} 时,自动打开 GET stream/{tid} 拉 event', async () => {
    let postCalled = false
    let streamCalled = false
    const fakeTaskId = 'a1b2c3d4-e5f6-7890-abcd-ef1234567890'
    server.use(
      http.post(`${API_BASE}/api/v0/chat`, () => {
        postCalled = true
        return MswHttpResponse.json({
          task_id: fakeTaskId,
          session_id: 's1',
          stream_url: `/api/v0/chat/stream/${fakeTaskId}`,
        })
      }),
      http.get(`${API_BASE}/api/v0/chat/stream/${fakeTaskId}`, () => {
        streamCalled = true
        return sseResponse([
          { type: 'token', seq: 1, content: 'hi' },
          { type: 'done', seq: 2 },
        ])
      }),
    )

    const { result } = renderHook(() => useChatSSE({ sessionId: 's1' }))
    await act(async () => {
      await result.current.sendMessage('hi')
    })
    expect(postCalled).toBe(true)
    expect(streamCalled).toBe(true)
    // After done event the assistant message is flushed; typewriter+flush
    // ensures the 'hi' chars reached either streamingDraft (mid-flight) or
    // the persisted messages list (post-done).
    await waitFor(() => {
      const s = snapshot(currentChatState)
      const hasToken =
        s.streamingDraft.includes('hi') ||
        s.messages.some((m) => m.content.includes('hi') && m.role === 'assistant')
      expect(hasToken).toBe(true)
    })
  })

  it('POST 返回 SSE (Plan 1 legacy) 时,沿用现有 consume 流程,不调 stream endpoint', async () => {
    let getStreamCalled = false
    server.use(
      http.post(`${API_BASE}/api/v0/chat`, () =>
        sseResponse([
          { type: 'token', seq: 1, content: 'legacy' },
          { type: 'done', seq: 2 },
        ]),
      ),
      // If hook (wrongly) calls /chat/stream/* on Plan 1 path, this trips.
      http.get(`${API_BASE}/api/v0/chat/stream/:tid`, () => {
        getStreamCalled = true
        return new MswHttpResponse(null, { status: 500 })
      }),
    )

    const { result } = renderHook(() => useChatSSE({ sessionId: 's1' }))
    await act(async () => {
      await result.current.sendMessage('hello')
    })

    expect(getStreamCalled).toBe(false)
    await waitFor(() => {
      const s = snapshot(currentChatState)
      const hasToken =
        s.streamingDraft.includes('legacy') ||
        s.messages.some(
          (m) => m.content.includes('legacy') && m.role === 'assistant',
        )
      expect(hasToken).toBe(true)
    })
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

describe('useChatSSE — delayed refetch on SSE done', () => {
  beforeEach(() => {
    currentChatActions.reset()
    currentChatActions.setSession('s1', [])
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('calls loadSessions immediately on done, then again ~3s later', async () => {
    const loadSessionsSpy = vi
      .spyOn(chatSessionsStore.chatSessionsActions, 'loadSessions')
      .mockResolvedValue(undefined)

    // Capture the 3s delayed callback without blocking the real typewriter timers.
    // We spy on window.setTimeout and intercept only the 3000ms call.
    let delayedCallback: (() => void) | null = null
    const origSetTimeout = window.setTimeout.bind(window)
    vi.spyOn(window, 'setTimeout').mockImplementation(
      (cb: TimerHandler, delay?: number, ...args: unknown[]) => {
        if (delay === 3000 && typeof cb === 'function') {
          delayedCallback = cb as () => void
          return 0 as unknown as ReturnType<typeof setTimeout>
        }
        return origSetTimeout(cb, delay, ...args)
      },
    )

    server.use(
      http.post(`${API_BASE}/api/v0/chat`, () =>
        sseResponse([
          { type: 'token', seq: 1, content: 'Hi' },
          { type: 'done', seq: 2 },
        ]),
      ),
    )

    const { result } = renderHook(() => useChatSSE({ sessionId: 's1' }))

    // Complete the stream — immediate refetch fires here
    await act(async () => {
      await result.current.sendMessage('hello')
    })

    // Immediate refetch fires on SSE done
    expect(loadSessionsSpy).toHaveBeenCalledTimes(1)
    // Delayed callback should have been registered
    expect(delayedCallback).not.toBeNull()

    // Manually fire the delayed callback
    await act(async () => {
      delayedCallback!()
    })

    expect(loadSessionsSpy).toHaveBeenCalledTimes(2)
  })

  it('does not fire delayed refetch if stream was aborted before done', async () => {
    const loadSessionsSpy = vi
      .spyOn(chatSessionsStore.chatSessionsActions, 'loadSessions')
      .mockResolvedValue(undefined)

    let delayedCallback: (() => void) | null = null
    const origSetTimeout = window.setTimeout.bind(window)
    vi.spyOn(window, 'setTimeout').mockImplementation(
      (cb: TimerHandler, delay?: number, ...args: unknown[]) => {
        if (delay === 3000 && typeof cb === 'function') {
          delayedCallback = cb as () => void
          return 0 as unknown as ReturnType<typeof setTimeout>
        }
        return origSetTimeout(cb, delay, ...args)
      },
    )

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
    ctrl.disconnect()
    await send.catch(() => {})

    // No done event seen — neither immediate nor delayed refetch fires
    expect(loadSessionsSpy).toHaveBeenCalledTimes(0)
    expect(delayedCallback).toBeNull()
  })
})
