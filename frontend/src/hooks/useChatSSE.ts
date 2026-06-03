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
  cancelChatTask,
  getChat,
  retryChatTask,
  type ChatPostJsonResponse,
} from '@/api/chatApi'
import {
  currentChatActions,
  currentChatState,
} from '@/store/current-chat'
import { chatSessionsActions } from '@/store/chat-sessions'
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
  // Plan 2 Scenario B: 切 session 回来时如果 GET /chats/{sid} 返回 active_task_id,
  // 调本 method subscribe in-flight stream;继续接收剩余 token + done event。
  // last_event_id='0' = from start;若前端记得上次的 entry_id 传它续读。
  subscribeToTask(taskId: string, lastEventId?: string): Promise<void>
  // Plan 3 Task 7: cancel in-flight task。POST /chat/cancel/{tid} → 202,
  // worker 内 listener 接 Redis pub/sub → graph 节点拦截 → partial commit。
  // 前端同时 abort 当前 SSE fetch 防 stale frame。
  cancelTask(taskId: string): Promise<void>
  // Plan 3 Task 7: retry from checkpoint。POST /chat/retry/{tid} → 拿新
  // task_id + stream_url,自动 abort 旧 stream → 立刻 subscribe 新 stream。
  retryTask(taskId: string): Promise<void>
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
  /** Called each time a valid SSE frame is parsed. Used by the idle watchdog
   *  (chat-send-02) to reset the no-frames timer on every received event. */
  onFrame?: () => void,
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
        // Notify caller (idle watchdog) that a frame arrived.
        onFrame?.()
        if (ev.type === 'token') {
          // Plan 2 dogfood root cause: backend SSE event JSON payload 没 seq 字段
          // (`{type:token, text, content}`),`ev.seq` = undefined → `undefined > 0`
          // = false → token 被 dedup 跳过 → typewriter 从未 enqueue → 用户看不到流式。
          // Plan 1 inline SSE 用 StreamEvent.model_dump 带 seq,Plan 2 直接 Redis
          // Stream payload 不带。修补:只在 seq 存在且 ≤ last_seq 时 skip(真重复),
          // 其他情况都 enqueue。
          const evSeq = (ev as { seq?: number }).seq
          if (typeof evSeq === 'number' && evSeq <= currentChatState.last_seq) {
            // dedup: 重复 event 跳过
          } else {
            if (typeof evSeq === 'number') {
              currentChatState.last_seq = evSeq
            }
            typewriter.enqueue((ev as TokenEvent).content ?? '')
          }
        } else {
          if (ev.type === 'done' || ev.type === 'error') {
            // dogfood fix: 等 typewriter natural RAF 排空再 dispatch done。
            // 之前用 sync flush 会瞬间排空 streamingDraft → user 看不到打字机过程。
            // 现在 await drained() 让 RAF 按 30 chars/s 自然吐字,完成后 dispatch
            // done → flushDraftAsMessage 入 messages。
            await typewriter.drained()
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
  // === NEW (2026-05-17): delayed sidebar refetch timer ref for cleanup on unmount ===
  const titleRefetchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Bug chat-send-02 (watchdog): if no SSE frame arrives within this many ms
  // the stream is considered hung; we abort + reset UI so the user can retry.
  // Value chosen to be longer than typical first-token latency (~30-60s) but
  // short enough to avoid an indefinite wait when the backend hangs silently.
  const STREAM_IDLE_TIMEOUT_MS = 90_000

  // Ref to the current idle watchdog timer so we can cancel it on each frame.
  const idleWatchdogRef = useRef<ReturnType<typeof setTimeout> | null>(null)

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
    return () => {
      // Clear delayed refetch timer on unmount to avoid late-firing after nav.
      if (titleRefetchTimerRef.current !== null) {
        clearTimeout(titleRefetchTimerRef.current)
        titleRefetchTimerRef.current = null
      }
      // Clear idle watchdog on unmount.
      if (idleWatchdogRef.current !== null) {
        clearTimeout(idleWatchdogRef.current)
        idleWatchdogRef.current = null
      }
    }
  }, [options.sessionId])

  const sendMessage = useCallback(
    async (
      content: string,
      forced?: { forced_tool_name: string; forced_tool_args: Record<string, unknown> },
    ) => {
      const sessionId = sessionIdRef.current
      if (!sessionId) throw new Error('sendMessage: no active session')
      abortRef.current?.abort()
      const ac = new AbortController()
      abortRef.current = ac

      currentChatActions.appendUserMessage(content)
      currentChatActions.beginStreaming()

      let doneSeen = false

      // Bug chat-send-02 (watchdog): arm an idle watchdog that fires if no SSE
      // frame arrives (or the POST itself doesn't resolve) within the timeout.
      // Each received SSE frame resets the timer via resetIdleWatchdog().
      // On fire: abort the request AND reset UI so the user is not stuck.
      const armIdleWatchdog = () => {
        if (idleWatchdogRef.current !== null) clearTimeout(idleWatchdogRef.current)
        idleWatchdogRef.current = setTimeout(() => {
          idleWatchdogRef.current = null
          ac.abort()
          currentChatActions.resetStreaming()
        }, STREAM_IDLE_TIMEOUT_MS)
      }
      const clearIdleWatchdog = () => {
        if (idleWatchdogRef.current !== null) {
          clearTimeout(idleWatchdogRef.current)
          idleWatchdogRef.current = null
        }
      }
      armIdleWatchdog()

      try {
        const res = await fetchImpl(buildChatPostUrl(), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_id: sessionId, message: content, ...(forced ?? {}) }),
          signal: ac.signal,
        })
        if (!res.ok) throw new Error(`POST /api/v0/chat ${res.status}`)

        const contentType = res.headers.get('content-type') ?? ''

        if (contentType.includes('application/json')) {
          // ===== Plan 2 path =====
          const json = (await res.json()) as ChatPostJsonResponse
          // Plan 3 Task 7: track in-flight task_id for cancel button + ChatPane UI
          currentChatActions.setActiveTaskId(json.task_id)
          const streamUrl = buildChatTaskStreamUrl(json.task_id, '0')
          const streamRes = await fetchImpl(streamUrl, { signal: ac.signal })
          if (!streamRes.ok) {
            throw new Error(`GET stream ${streamRes.status}`)
          }
          const result = await consumeStream(
            streamRes,
            ac.signal,
            typewriterRef.current,
            armIdleWatchdog,
          )
          doneSeen = result.doneSeen
        } else {
          // ===== Plan 1 path (legacy SSE inline) =====
          const result = await consumeStream(
            res,
            ac.signal,
            typewriterRef.current,
            armIdleWatchdog,
          )
          doneSeen = result.doneSeen
        }

        // Stream completed normally — clear the idle watchdog.
        clearIdleWatchdog()
        // Flush any remaining typewriter chars so the persisted assistant
        // message captures the full token stream (dispatchEvent('done') already
        // ran flushDraftAsMessage with whatever streamingDraft had at the time;
        // we flush typewriter BEFORE done arrives via consumeStream — but the
        // RAF loop is async, so chars may still be queued. Drain them here.)
        typewriterRef.current.flush()
      } catch {
        clearIdleWatchdog()
        if (ac.signal.aborted) return
      }

      if (doneSeen && !ac.signal.aborted) {
        // === NEW (2026-05-17): 双阶段 sidebar 刷新 ===
        // 第一次: SSE done 后立刻刷 sidebar,让 last_msg_preview 即时更新。
        void chatSessionsActions.loadSessions()
        // 第二次: 延迟 3s 再刷,等 Celery generate_session_title task 完成
        // (countdown=1 + ~1-2s LLM call),让 LLM 生成的 title 出现在 sidebar。
        if (titleRefetchTimerRef.current !== null) {
          clearTimeout(titleRefetchTimerRef.current)
        }
        titleRefetchTimerRef.current = setTimeout(() => {
          titleRefetchTimerRef.current = null
          void chatSessionsActions.loadSessions()
        }, 3000)
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
          // C68: double-failure (stream error + getChat error) — surface error instead
          // of leaving streamingStatus stuck at 'reconnecting' indefinitely.
          if (!ac.signal.aborted) {
            currentChatActions.dispatchEvent({
              type: 'error',
              seq: currentChatState.last_seq + 1,
              error: '连接断开，请重试。',
            })
          }
        }
      }
    },
    [fetchImpl],
  )

  const abort = useCallback(() => {
    abortRef.current?.abort()
    // Bug chat-send-02: abort must reset the UI to idle so the user can send
    // another message. Previously abort() only triggered the AbortController
    // without touching any store state, leaving streamingStatus stuck at
    // 'streaming' forever when the abort path was reached before active_task_id
    // was set (POST still pending) or when the backend never sent a done frame.
    currentChatActions.resetStreaming()
  }, [])

  const status = useCallback(
    () => currentChatState.streamingStatus,
    [],
  )

  // Plan 2 Scenario B: 重连 in-flight stream(切 session 回来 / 重开页面时)。
  // sendMessage 的子集 — 跳过 POST,直接 GET stream/{task_id}?last_event_id=X。
  const subscribeToTask = useCallback(
    async (taskId: string, lastEventId: string = '0') => {
      abortRef.current?.abort()
      const ac = new AbortController()
      abortRef.current = ac

      currentChatActions.beginStreaming()

      let doneSeen = false
      try {
        const streamUrl = buildChatTaskStreamUrl(taskId, lastEventId)
        const streamRes = await fetchImpl(streamUrl, { signal: ac.signal })
        if (!streamRes.ok) {
          // 404 (task 不存在 / 已 GC) 或 503 (no Redis) — 静默退出,user 看到的还是
          // GET /chats/{sid} 拉的 PG 历史
          return
        }
        const result = await consumeStream(
          streamRes,
          ac.signal,
          typewriterRef.current,
        )
        doneSeen = result.doneSeen
      } catch {
        if (ac.signal.aborted) return
      }
      if (!doneSeen) {
        typewriterRef.current.flush()
      }
    },
    [fetchImpl],
  )

  // Plan 3 Task 7: cancel in-flight task。POST /chat/cancel/{tid} → 202;
  // worker 内 listener 接 Redis pub/sub → graph 节点拦截 → partial commit。
  // 前端同时 abort 当前 SSE fetch 防 stale frame。
  const cancelTask = useCallback(async (taskId: string) => {
    abortRef.current?.abort()
    try {
      await cancelChatTask(taskId)
    } catch {
      // 失败也 reset UI(用户感知 cancel 了)
    }
    // Bug chat-send-02 follow-up: cancelTask previously only cleared
    // active_task_id but left streamingStatus at 'streaming'. Use the same
    // resetStreaming() action so cancel always brings the UI back to idle,
    // regardless of whether the cancelled SSE frame arrives or not.
    currentChatActions.resetStreaming()
  }, [])

  // Plan 3 Task 7: retry from checkpoint。POST /chat/retry/{tid} → 新 task_id
  // + stream_url → 自动 abort 旧 + 立刻 subscribe 新 task stream(typewriter 接续)。
  const retryTask = useCallback(
    async (taskId: string) => {
      abortRef.current?.abort()
      try {
        const resp = await retryChatTask(taskId)
        currentChatActions.setActiveTaskId(resp.task_id)
        // 调内部 subscribeToTask 复用 stream consume 逻辑
        await subscribeToTask(resp.task_id, '0')
      } catch {
        // 失败留 UI 在 error 状态;用户可以再点 retry
      }
    },
    [subscribeToTask],
  )

  return { sendMessage, abort, status, subscribeToTask, cancelTask, retryTask }
}
