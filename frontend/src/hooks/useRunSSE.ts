import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  cancelRun as cancelRunRequest,
  createRun,
  fetchRunEvents,
  getRun,
  getRunSession,
  resumeRun as resumeRunRequest,
  type RunResponse,
  type RunStatus,
} from '@/api/runApi'
import { chatSessionsActions } from '@/store/chat-sessions'
import { currentChatActions } from '@/store/current-chat'

const TERMINAL = new Set<RunStatus>(['completed', 'failed', 'cancelled'])
const ACTIVE = new Set<RunStatus>([
  'queued',
  'assigned',
  'running',
  'cancel_requested',
])

interface UseRunSSEOptions {
  tenantId: string | null
  sessionId: string | null
  fetchImpl?: typeof fetch
  delayMs?: (ms: number) => Promise<void>
  maxReconnectAttempts?: number
  onSessionCreated?: (sessionId: string) => void
  initialRunId?: string | null
  initialRunStatus?: RunStatus | null
  initialPause?: RunPause | null
}

export interface UseRunSSE {
  sendPrompt(prompt: string): Promise<void>
  cancelRun(): Promise<void>
  resumeRun(response: Record<string, unknown>): Promise<void>
  resubmitPrompt(prompt: string, replacesRunId: string): Promise<void>
  abort(): void
  status: RunStatus | 'idle' | 'error'
  activeRunId: string | null
  pause: RunPause | null
}

export interface RunPause {
  type: 'approval_request' | 'input_request'
  request: Record<string, unknown>
}

interface ParsedSseEvent {
  id: string | null
  event: string
  data: Record<string, unknown>
}

function parseFrame(frame: string): ParsedSseEvent | null {
  let id: string | null = null
  let event = 'message'
  const data: string[] = []
  for (const line of frame.split(/\r?\n/)) {
    if (!line || line.startsWith(':')) continue
    const separator = line.indexOf(':')
    const field = separator < 0 ? line : line.slice(0, separator)
    let value = separator < 0 ? '' : line.slice(separator + 1)
    if (value.startsWith(' ')) value = value.slice(1)
    if (field === 'id') id = value
    else if (field === 'event') event = value
    else if (field === 'data') data.push(value)
  }
  if (data.length === 0) return null
  try {
    return { id, event, data: JSON.parse(data.join('\n')) as Record<string, unknown> }
  } catch {
    return null
  }
}

async function consumeSse(
  response: Response,
  signal: AbortSignal,
  onEvent: (event: ParsedSseEvent) => boolean,
): Promise<boolean> {
  const reader = response.body?.getReader()
  if (!reader) return false
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    while (!signal.aborted) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let boundary = buffer.match(/\r?\n\r?\n/)
      while (boundary?.index !== undefined) {
        const frame = buffer.slice(0, boundary.index)
        buffer = buffer.slice(boundary.index + boundary[0].length)
        const parsed = parseFrame(frame)
        if (parsed && onEvent(parsed)) {
          await reader.cancel()
          return true
        }
        boundary = buffer.match(/\r?\n\r?\n/)
      }
    }
  } finally {
    if (signal.aborted) await reader.cancel().catch(() => {})
  }
  return false
}

function idempotencyKey(): string {
  return globalThis.crypto?.randomUUID?.() ?? `web-${Date.now()}-${Math.random()}`
}

export function useRunSSE(options: UseRunSSEOptions): UseRunSSE {
  const fetchImpl = options.fetchImpl ?? fetch
  const onSessionCreated = options.onSessionCreated
  const delayMs = useMemo(
    () => options.delayMs ?? ((ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms))),
    [options.delayMs],
  )
  const maxReconnectAttempts = options.maxReconnectAttempts ?? 3
  const abortRef = useRef<AbortController | null>(null)
  const generationRef = useRef(0)
  const activeRunRef = useRef<string | null>(null)
  const lastRunRef = useRef<string | null>(null)
  const revisionBaseRef = useRef<string | null>(null)
  const statusRef = useRef<RunStatus | 'idle' | 'error'>('idle')
  const sessionRef = useRef(options.sessionId)
  const tenantRef = useRef(options.tenantId)
  const cursorRef = useRef<string | null>(null)
  const seenIdsRef = useRef(new Set<string>())
  const [status, setStatus] = useState<RunStatus | 'idle' | 'error'>('idle')
  const [activeRunId, setActiveRunId] = useState<string | null>(null)
  const [pause, setPause] = useState<RunPause | null>(options.initialPause ?? null)

  sessionRef.current = options.sessionId ?? sessionRef.current
  tenantRef.current = options.tenantId

  const isCurrent = useCallback(
    (generation: number, signal?: AbortSignal) =>
      generationRef.current === generation && !signal?.aborted,
    [],
  )

  const updateStatus = useCallback((next: RunStatus | 'idle' | 'error') => {
    statusRef.current = next
    setStatus(next)
    if (next !== 'idle' && next !== 'error') currentChatActions.setRunStatus(next)
  }, [])

  const updateActiveRun = useCallback((runId: string | null, runStatus: RunStatus | null) => {
    activeRunRef.current = runId
    if (runId) lastRunRef.current = runId
    setActiveRunId(runId)
    currentChatActions.setActiveRun(runId, runStatus)
  }, [])

  const loadDurableHistory = useCallback(
    async (tenantId: string, sessionId: string, generation: number, signal: AbortSignal) => {
      const session = await getRunSession(tenantId, sessionId, fetchImpl)
      if (!isCurrent(generation, signal)) return
      currentChatActions.replaceWithDurableMessages(sessionId, session.messages)
      void chatSessionsActions.loadSessions()
    },
    [fetchImpl, isCurrent],
  )

  const calibrate = useCallback(
    async (
      tenantId: string,
      runId: string,
      sessionId: string,
      generation: number,
      signal: AbortSignal,
    ): Promise<RunResponse | null> => {
      const run = await getRun(tenantId, runId, fetchImpl)
      if (!isCurrent(generation, signal)) return null
      updateStatus(run.status)
      if (TERMINAL.has(run.status)) {
        await loadDurableHistory(tenantId, sessionId, generation, signal)
        if (!isCurrent(generation, signal)) return null
        updateActiveRun(null, run.status)
        currentChatActions.finishRun(run.status)
        if (run.status === 'completed') revisionBaseRef.current = null
      }
      return run
    },
    [fetchImpl, isCurrent, loadDurableHistory, updateActiveRun, updateStatus],
  )

  const streamRun = useCallback(
    async (
      tenantId: string,
      runId: string,
      sessionId: string,
      generation: number,
      controller: AbortController,
    ) => {
      let reconnectAttempt = 0
      while (isCurrent(generation, controller.signal)) {
        let terminalFrame = false
        let streamError: unknown = null
        try {
          const response = await fetchRunEvents(tenantId, runId, {
            lastEventId: cursorRef.current,
            signal: controller.signal,
            fetchImpl,
          })
          if (!isCurrent(generation, controller.signal)) return
          terminalFrame = await consumeSse(response, controller.signal, (event) => {
            if (!isCurrent(generation, controller.signal)) return true
            if (event.id) {
              if (seenIdsRef.current.has(event.id)) return false
              seenIdsRef.current.add(event.id)
              cursorRef.current = event.id
              currentChatActions.setLastEventId(event.id)
            }
            if (event.event === 'token') {
              const content = event.data.content ?? event.data.text
              if (typeof content === 'string') currentChatActions.appendRunToken(content)
            } else if (event.event === 'approval_request' || event.event === 'input_request') {
              setPause({ type: event.event, request: event.data })
            } else if (event.event === 'run.completed') {
              const content = event.data.content
              currentChatActions.finishRun(
                'completed',
                typeof content === 'string' ? content : undefined,
              )
              return true
            } else if (event.event === 'run.failed') {
              currentChatActions.failRun(String(event.data.error_message ?? 'Run failed'))
              return true
            } else if (event.event === 'run.cancelled') {
              currentChatActions.finishRun('cancelled')
              return true
            } else if (event.event === 'run.paused') {
              const pauseType = event.data.pause_type
              const request = event.data.request
              if (
                (pauseType === 'approval' || pauseType === 'input') &&
                request && typeof request === 'object' && !Array.isArray(request)
              ) {
                setPause({
                  type: pauseType === 'approval' ? 'approval_request' : 'input_request',
                  request: request as Record<string, unknown>,
                })
              }
              return true
            }
            return false
          })
        } catch (error) {
          if (!isCurrent(generation, controller.signal)) return
          streamError = error
        }

        if (!isCurrent(generation, controller.signal)) return
        let calibrated: RunResponse | null = null
        try {
          calibrated = await calibrate(
            tenantId,
            runId,
            sessionId,
            generation,
            controller.signal,
          )
        } catch (error) {
          streamError ??= error
        }
        if (!isCurrent(generation, controller.signal)) return
        if (calibrated && (TERMINAL.has(calibrated.status) || !ACTIVE.has(calibrated.status))) {
          return
        }
        if (terminalFrame && calibrated === null) return
        if (reconnectAttempt >= maxReconnectAttempts) {
          const message = streamError instanceof Error ? streamError.message : 'Run stream disconnected'
          currentChatActions.failRun(message)
          updateActiveRun(null, 'failed')
          updateStatus('error')
          return
        }
        currentChatActions.setReconnecting()
        const wait = Math.min(100 * 2 ** reconnectAttempt, 1000)
        reconnectAttempt += 1
        await delayMs(wait)
      }
    },
    [
      calibrate,
      delayMs,
      fetchImpl,
      isCurrent,
      maxReconnectAttempts,
      updateActiveRun,
      updateStatus,
    ],
  )

  const startRun = useCallback(
    async (prompt: string, replacesRunId?: string) => {
      const tenantId = tenantRef.current
      if (!tenantId) {
        currentChatActions.failRun('No active tenant')
        updateStatus('error')
        return
      }
      if (activeRunRef.current) {
        return
      }
      generationRef.current += 1
      const generation = generationRef.current
      abortRef.current?.abort()
      const controller = new AbortController()
      abortRef.current = controller
      cursorRef.current = null
      seenIdsRef.current = new Set()
      currentChatActions.beginRun(prompt)
      setPause(null)
      updateStatus('queued')
      try {
        const replacement = replacesRunId ?? revisionBaseRef.current
        const created = await createRun(
          tenantId,
          {
            session_id: sessionRef.current,
            prompt,
            ...(replacement ? { replaces_run_id: replacement } : {}),
          },
          idempotencyKey(),
          fetchImpl,
        )
        if (!isCurrent(generation, controller.signal)) return
        revisionBaseRef.current = null
        if (!sessionRef.current) {
          sessionRef.current = created.session_id
          currentChatActions.adoptRunSession(created.session_id)
        }
        updateActiveRun(created.id, created.status)
        updateStatus(created.status)
        if (options.sessionId === null) {
          onSessionCreated?.(created.session_id)
          void chatSessionsActions.loadSessions()
        }
        await streamRun(
          tenantId,
          created.id,
          created.session_id,
          generation,
          controller,
        )
      } catch (error) {
        if (!isCurrent(generation, controller.signal)) return
        currentChatActions.failRun(error instanceof Error ? error.message : 'Run failed')
        updateActiveRun(null, 'failed')
        updateStatus('error')
      }
    },
    [fetchImpl, isCurrent, onSessionCreated, options.sessionId, streamRun, updateActiveRun, updateStatus],
  )

  const cancelRun = useCallback(async () => {
    const tenantId = tenantRef.current
    const runId = activeRunRef.current
    const sessionId = sessionRef.current
    if (!tenantId || !runId || !sessionId) return
    generationRef.current += 1
    const generation = generationRef.current
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    revisionBaseRef.current = runId
    setPause(null)
    try {
      const cancelled = await cancelRunRequest(tenantId, runId, fetchImpl)
      if (!isCurrent(generation, controller.signal)) return
      updateStatus(cancelled.status)
      if (TERMINAL.has(cancelled.status)) {
        updateActiveRun(null, cancelled.status)
        currentChatActions.finishRun(cancelled.status)
        await loadDurableHistory(tenantId, sessionId, generation, controller.signal)
        return
      }
      await streamRun(tenantId, runId, sessionId, generation, controller)
    } catch (error) {
      if (!isCurrent(generation, controller.signal)) return
      currentChatActions.reportRunTransportError(
        error instanceof Error ? error.message : 'Cancel failed',
      )
      updateStatus('error')
    }
  }, [fetchImpl, isCurrent, loadDurableHistory, streamRun, updateActiveRun, updateStatus])

  const resumeRun = useCallback(
    async (response: Record<string, unknown>) => {
      const tenantId = tenantRef.current
      const runId = activeRunRef.current ?? lastRunRef.current
      const sessionId = sessionRef.current
      if (!tenantId || !runId || !sessionId) return
      generationRef.current += 1
      const generation = generationRef.current
      abortRef.current?.abort()
      const controller = new AbortController()
      abortRef.current = controller
      try {
        const resumed = await resumeRunRequest(tenantId, runId, response, fetchImpl)
        if (!isCurrent(generation, controller.signal)) return
        setPause(null)
        updateActiveRun(runId, resumed.status)
        updateStatus(resumed.status)
        await streamRun(tenantId, runId, sessionId, generation, controller)
      } catch (error) {
        if (!isCurrent(generation, controller.signal)) return
        currentChatActions.reportRunTransportError(
          error instanceof Error ? error.message : 'Resume failed',
        )
        updateStatus('error')
      }
    },
    [fetchImpl, isCurrent, streamRun, updateActiveRun, updateStatus],
  )

  const abort = useCallback(() => {
    generationRef.current += 1
    abortRef.current?.abort()
    abortRef.current = null
    updateActiveRun(null, null)
    updateStatus('idle')
    currentChatActions.resetRunTransport()
  }, [updateActiveRun, updateStatus])

  useEffect(() => {
    const tenantId = options.tenantId
    const sessionId = options.sessionId
    const runId = options.initialRunId
    const runStatus = options.initialRunStatus
    if (!tenantId || !sessionId || !runId || !runStatus || activeRunRef.current) return
    generationRef.current += 1
    const generation = generationRef.current
    const controller = new AbortController()
    abortRef.current?.abort()
    abortRef.current = controller
    cursorRef.current = null
    seenIdsRef.current = new Set()
    updateActiveRun(runId, runStatus)
    updateStatus(runStatus)
    setPause(options.initialPause ?? null)
    void streamRun(tenantId, runId, sessionId, generation, controller)
  }, [
    options.initialRunId,
    options.initialRunStatus,
    options.initialPause,
    options.sessionId,
    options.tenantId,
    streamRun,
    updateActiveRun,
    updateStatus,
  ])

  useEffect(() => {
    return () => {
      generationRef.current += 1
      abortRef.current?.abort()
    }
  }, [options.sessionId, options.tenantId])

  return {
    sendPrompt: (prompt) => startRun(prompt),
    cancelRun,
    resumeRun,
    resubmitPrompt: (prompt, replacesRunId) => startRun(prompt, replacesRunId),
    abort,
    status,
    activeRunId,
    pause,
  }
}
