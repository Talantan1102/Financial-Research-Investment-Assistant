/**
 * frontend/src/hooks/useChatSSE.ts
 *
 * SSE consumer for chat. Plan 2 双 path graceful degrade:
 *
 *   Plan 1 (legacy):POST /api/v0/chat 直接返 text/event-stream → 现有 consume.
 *   Plan 2 (enqueue):POST /api/v0/chat 返 application/json
 *     `{task_id, session_id, stream_url}` → 自动打开
 *     GET /api/v0/chat/stream/{task_id} (SSE replay from Redis Streams).
 *
 * 分流逻辑只看 response Content-Type。后端 redis_async wired → Plan 2;否则
 * 自动 fallback Plan 1。前端无感知,组件 sendMessage(content) 接口不变。
 *
 * Plan 2 spec § 6.5:token event 走 RAF + char queue 打字机 (useTypewriter),
 * 把后端 chunk-level chunk 拆成字符渲染,视觉等同 token-level 流。
 *
 * 其它行为:
 *   - 断流时一次性 GET /api/v0/chats/:id reload 历史 (Plan 1 修补)
 *   - session swap → abort 旧 stream (F8)
 */

import { useCallback, useEffect, useRef } from 'react'
import {
  buildChatPostUrl,
  buildChatTaskStreamUrl,
  getChat,
  type ChatPostJsonResponse,
} from '@/api/chatApi'
import {
  currentChatActions,
  currentChatState,
} from '@/store/current-chat'
import type { SSEEvent, TokenEvent } from '@/types/chat'
import { useTypewriter } from './useTypewriter'

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

interface Typewriter {
  enqueue: (text: string) => void
  flush: () => void
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
  typewriter: Typewriter,
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
        if (ev.type === 'token') {
          // Plan 2 Task 6:token 不走 dispatchEvent,改入 typewriter queue,
          // 由 RAF loop 逐字符 push 进 streamingDraft。bump last_seq 仍需 do —
          // 否则 abort / reconnect 时序判断失效。
          if (ev.seq > currentChatState.last_seq) {
            currentChatState.last_seq = ev.seq
            typewriter.enqueue((ev as TokenEvent).content ?? '')
          }
        } else {
          if (ev.type === 'done' || ev.type === 'error') {
            // Drain typewriter SYNC before dispatch — dispatchEvent('done')
            // calls flushDraftAsMessage which snapshots streamingDraft into
            // the persisted assistant message;若 typewriter 还有 char 没吐,
            // 会丢字。先 flush 保证 streamingDraft 完整。
            typewriter.flush()
            doneSeen = true
          }
          currentChatActions.dispatchEvent(ev)
        }
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

  const typewriter = useTypewriter({
    onChar: (ch) => {
      currentChatState.streamingDraft += ch
    },
  })
  // Keep latest typewriter ref to avoid re-creating sendMessage when typewriter
  // identity changes between renders (it shouldn't, but defensive).
  const typewriterRef = useRef(typewriter)
  typewriterRef.current = typewriter

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
          body: JSON.stringify({ session_id: sessionId, message: content }),
          signal: ac.signal,
        })
        if (!res.ok) throw new Error(`POST /api/v0/chat ${res.status}`)

        const contentType = res.headers.get('content-type') ?? ''

        if (contentType.includes('application/json')) {
          // ===== Plan 2 path =====
          const json = (await res.json()) as ChatPostJsonResponse
          const streamUrl = buildChatTaskStreamUrl(json.task_id, '0')
          const streamRes = await fetchImpl(streamUrl, { signal: ac.signal })
          if (!streamRes.ok) {
            throw new Error(`GET stream ${streamRes.status}`)
          }
          const result = await consumeStream(
            streamRes,
            ac.signal,
            typewriterRef.current,
          )
          doneSeen = result.doneSeen
        } else {
          // ===== Plan 1 path (legacy SSE inline) =====
          const result = await consumeStream(
            res,
            ac.signal,
            typewriterRef.current,
          )
          doneSeen = result.doneSeen
        }

        // Flush any remaining typewriter chars so the persisted assistant
        // message captures the full token stream (dispatchEvent('done') already
        // ran flushDraftAsMessage with whatever streamingDraft had at the time;
        // we flush typewriter BEFORE done arrives via consumeStream — but the
        // RAF loop is async, so chars may still be queued. Drain them here.)
        typewriterRef.current.flush()
      } catch {
        if (ac.signal.aborted) return
      }

      if (!doneSeen && !ac.signal.aborted) {
        // 流断了 — Plan 1 修补行为:reload 历史 (Plan 2 task 9 会强化此分支)。
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
