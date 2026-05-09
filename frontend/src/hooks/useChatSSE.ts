/**
 * frontend/src/hooks/useChatSSE.ts
 *
 * SSE consumer for chat. Encapsulates:
 *   - POST /api/v0/chat (initial message) — fetch + ReadableStream
 *   - GET  /api/v0/chat/stream/:id?last_event_id=N (reconnect)
 *   - parse `id: <seq>\nevent: <type>\ndata: <json>\n\n` frames
 *   - dispatch each event into currentChatStore
 *   - on disconnect: exponential backoff retry until done event seen or aborted
 *   - on session swap: abort previous, reset state, start fresh (F8)
 *
 * Plan 4a exposes:  { sendMessage, abort, status }
 * Plan 4b consumes the same surface unchanged.
 */

import { useCallback, useEffect, useRef } from 'react'
import {
  buildChatPostUrl,
  buildChatStreamUrl,
} from '@/api/chatApi'
import {
  currentChatActions,
  currentChatState,
} from '@/store/current-chat'
import type { SSEEvent } from '@/types/chat'
import { computeBackoffMs } from './useExponentialBackoff'

interface UseChatSSEOptions {
  sessionId: string | null
  fetchImpl?: typeof fetch
  delayMs?: (ms: number) => Promise<void>
}

interface UseChatSSE {
  sendMessage(content: string): Promise<void>
  abort(): void
  status: () => string
}

const SSE_FRAME_DELIMITER = '\n\n'

function parseFrame(frame: string): SSEEvent | null {
  let dataLine: string | null = null
  for (const line of frame.split('\n')) {
    if (line.startsWith('data: ')) dataLine = line.slice(6)
  }
  if (!dataLine) return null
  try {
    return JSON.parse(dataLine) as SSEEvent
  } catch {
    return null
  }
}

async function consumeStream(
  res: Response,
  signal: AbortSignal,
): Promise<{ doneSeen: boolean }> {
  const reader = res.body?.getReader()
  if (!reader) return { doneSeen: false }
  const decoder = new TextDecoder()
  let buffer = ''
  let doneSeen = false

  while (true) {
    if (signal.aborted) {
      reader.cancel().catch(() => {})
      break
    }
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let idx = buffer.indexOf(SSE_FRAME_DELIMITER)
    while (idx >= 0) {
      const frame = buffer.slice(0, idx)
      buffer = buffer.slice(idx + SSE_FRAME_DELIMITER.length)
      const ev = parseFrame(frame)
      if (ev) {
        currentChatActions.dispatchEvent(ev)
        if (ev.type === 'done' || ev.type === 'error') doneSeen = true
      }
      idx = buffer.indexOf(SSE_FRAME_DELIMITER)
    }
  }
  return { doneSeen }
}

function defaultDelay(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms))
}

export function useChatSSE(options: UseChatSSEOptions): UseChatSSE {
  const fetchImpl = options.fetchImpl ?? fetch
  const delay = options.delayMs ?? defaultDelay
  const abortRef = useRef<AbortController | null>(null)
  const sessionIdRef = useRef<string | null>(options.sessionId)

  useEffect(() => {
    if (sessionIdRef.current !== options.sessionId) {
      abortRef.current?.abort()
      sessionIdRef.current = options.sessionId
    }
  }, [options.sessionId])

  const sendMessage = useCallback(
    async (content: string) => {
      const sessionId = sessionIdRef.current
      if (!sessionId) throw new Error('sendMessage: no active session')
      abortRef.current?.abort()
      const ac = new AbortController()
      abortRef.current = ac

      currentChatActions.appendUserMessage(content)
      currentChatActions.beginStreaming()

      let attempt = 0
      let doneSeen = false

      try {
        const res = await fetchImpl(buildChatPostUrl(), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_id: sessionId, content }),
          signal: ac.signal,
        })
        if (!res.ok) throw new Error(`POST /api/v0/chat ${res.status}`)
        const result = await consumeStream(res, ac.signal)
        doneSeen = result.doneSeen
      } catch {
        if (ac.signal.aborted) return
      }

      while (!doneSeen && !ac.signal.aborted) {
        currentChatActions.setReconnecting()
        const backoffMs = computeBackoffMs(attempt++)
        await delay(backoffMs)
        if (ac.signal.aborted) return
        try {
          const url = buildChatStreamUrl(sessionId, currentChatState.last_seq)
          const res = await fetchImpl(url, { signal: ac.signal })
          if (!res.ok) continue
          currentChatActions.beginStreaming()
          const result = await consumeStream(res, ac.signal)
          doneSeen = result.doneSeen
        } catch {
          if (ac.signal.aborted) return
        }
      }
    },
    [delay, fetchImpl],
  )

  const abort = useCallback(() => {
    abortRef.current?.abort()
  }, [])

  const status = useCallback(
    () => currentChatState.streamingStatus,
    [],
  )

  return { sendMessage, abort, status }
}
