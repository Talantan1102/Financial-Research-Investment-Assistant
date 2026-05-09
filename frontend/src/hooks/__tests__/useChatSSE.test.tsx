import { http } from 'msw'
import { describe, expect, it, beforeEach } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { snapshot } from 'valtio'
import { useChatSSE } from '@/hooks/useChatSSE'
import { server } from '@/test-utils/msw-server'
import { sseResponse } from '@/test-utils/sse-mock'
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
