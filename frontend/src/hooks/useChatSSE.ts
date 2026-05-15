/**
 * frontend/src/hooks/useChatSSE.ts
 *
 * SSE consumer for chat. Encapsulates:
 *   - POST /api/v0/chat (initial message) — fetch + ReadableStream
 *   - parse `id: <seq>\nevent: <type>\ndata: <json>\n\n` frames
 *   - dispatch each event into currentChatStore
 *   - on disconnect: GET /api/v0/chats/:id to reload history (no in-flight subscribe yet — Plan 2)
 *   - on session swap: abort previous, reset state, start fresh (F8)
 *
 * Plan 4a exposes:  { sendMessage, abort, status }
 * Plan 4b consumes the same surface unchanged.
 */

import { useCallback, useEffect, useRef } from 'react'
import { buildChatPostUrl, getChat } from '@/api/chatApi'
import {
  currentChatActions,
  currentChatState,
} from '@/store/current-chat'
import type { SSEEvent } from '@/types/chat'

interface UseChatSSEOptions {
  sessionId: string | null
  fetchImpl?: typeof fetch
  // delayMs kept in the options shape for backward-compat with existing tests
  // (Plan 1 removed the reconnect backoff loop; Plan 2 may reintroduce it).
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
      if (signal.aborted) {
        reader.cancel().catch(() => {})
        return { doneSeen }
      }
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

export function useChatSSE(options: UseChatSSEOptions): UseChatSSE {
  const fetchImpl = options.fetchImpl ?? fetch
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

      // Plan 1: 不再轮询不存在的 GET /api/v0/chat/stream/:id endpoint。
      // 断流时改一次性 GET /api/v0/chats/:id 重载历史 messages —
      // backend Task 5 已在 finally 块持久化完整的 assistant message,
      // 通过 currentChatActions.setSession 替换 UI state。
      // Plan 2 会重新引入真正的 /chat/stream/{task_id} (Celery + Redis Streams)。
      if (!doneSeen && !ac.signal.aborted) {
        currentChatActions.setReconnecting()
        try {
          const fresh = await getChat(sessionId)
          if (!ac.signal.aborted) {
            currentChatActions.setSession(sessionId, fresh.messages)
          }
        } catch {
          // Silent — leave streamingStatus as reconnecting; next user action will retry.
        }
      }
    },
    [fetchImpl],
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
