import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { snapshot } from 'valtio'
import * as runApi from '@/api/runApi'
import { useRunSSE } from '@/hooks/useRunSSE'
import { currentChatActions, currentChatState } from '@/store/current-chat'
import { chatSessionsActions } from '@/store/chat-sessions'
import type { RunResponse, RunSessionDetail } from '@/api/runApi'

vi.mock('@/api/runApi', async () => {
  const actual = await vi.importActual<typeof import('@/api/runApi')>('@/api/runApi')
  return {
    ...actual,
    createRun: vi.fn(),
    fetchRunEvents: vi.fn(),
    getRun: vi.fn(),
    getRunSession: vi.fn(),
    cancelRun: vi.fn(),
    resumeRun: vi.fn(),
  }
})

function run(status: RunResponse['status'], id = 'run-1'): RunResponse {
  return {
    id,
    tenant_id: 'tenant-1',
    session_id: 'session-1',
    created_by_user_id: 'user-1',
    run_type: 'chat',
    status,
    replaces_run_id: null,
    retry_count: 0,
    created_at: '2026-07-18T00:00:00Z',
    queued_at: '2026-07-18T00:00:00Z',
    finished_at: status === 'completed' ? '2026-07-18T00:00:01Z' : null,
    error_code: null,
    error_message: null,
  }
}

function detail(content = 'Hello durable'): RunSessionDetail {
  return {
    id: 'session-1',
    tenant_id: 'tenant-1',
    created_by_user_id: 'user-1',
    title: 'Session',
    created_at: '2026-07-18T00:00:00Z',
    updated_at: '2026-07-18T00:00:01Z',
    archived_at: null,
    messages: [
      {
        id: 'message-1',
        role: 'assistant',
        content,
        status: 'complete',
        created_at: '2026-07-18T00:00:01Z',
      },
    ],
    has_more: false,
    active_run_id: null,
    active_run_status: null,
    active_pause_type: null,
    active_pause_request: null,
  }
}

function chunkedSse(chunks: string[]): Response {
  const encoder = new TextEncoder()
  return new Response(
    new ReadableStream({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
        controller.close()
      },
    }),
    { headers: { 'Content-Type': 'text/event-stream' } },
  )
}

describe('useRunSSE', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    currentChatActions.reset()
    chatSessionsActions.reset()
    vi.mocked(runApi.createRun).mockResolvedValue(run('queued'))
    vi.mocked(runApi.getRun).mockResolvedValue(run('completed'))
    vi.mocked(runApi.getRunSession).mockResolvedValue(detail())
    vi.spyOn(chatSessionsActions, 'loadSessions').mockResolvedValue(undefined)
  })

  it('does POST then GET events, parses cross-chunk multiline SSE, adopts session and calibrates durable history', async () => {
    vi.mocked(runApi.fetchRunEvents).mockResolvedValue(
      chunkedSse([
        'id: v1:1:1-0\nevent: token\ndata: {"content":',
        '\ndata: "Hello transient"}\n\n',
        'id: v1:2:1-1\nevent: run.completed\ndata: {"content":"Hello durable"}\n\n',
      ]),
    )
    const created: string[] = []
    const { result } = renderHook(() =>
      useRunSSE({
        tenantId: 'tenant-1',
        sessionId: null,
        onSessionCreated: (id) => created.push(id),
      }),
    )

    await act(async () => result.current.sendPrompt('analyze'))

    expect(runApi.createRun).toHaveBeenCalledWith(
      'tenant-1',
      expect.objectContaining({ session_id: null, prompt: 'analyze' }),
      expect.any(String),
      expect.any(Function),
      expect.any(AbortSignal),
    )
    expect(runApi.fetchRunEvents).toHaveBeenCalledAfter(runApi.createRun as never)
    expect(created).toEqual(['session-1'])
    const state = snapshot(currentChatState)
    expect(state.session_id).toBe('session-1')
    expect(state.last_event_id).toBe('v1:2:1-1')
    expect(state.messages.at(-1)?.content).toBe('Hello durable')
    expect(result.current.status).toBe('completed')
    expect(result.current.activeRunId).toBeNull()
  })

  it('reconnects with the opaque cursor unchanged, ignores duplicate frames and uses bounded backoff', async () => {
    vi.mocked(runApi.getRun)
      .mockResolvedValueOnce(run('running'))
      .mockResolvedValueOnce(run('completed'))
    vi.mocked(runApi.fetchRunEvents)
      .mockResolvedValueOnce(
        chunkedSse(['id: v1:7:99-3\nevent: token\ndata: {"content":"A"}\n\n']),
      )
      .mockResolvedValueOnce(
        chunkedSse([
          'id: v1:7:99-3\nevent: token\ndata: {"content":"A"}\n\n',
          'id: v1:8:99-4\nevent: run.completed\ndata: {"content":"AB"}\n\n',
        ]),
      )
    vi.mocked(runApi.getRunSession).mockResolvedValue(detail('AB'))
    const delays: number[] = []
    currentChatActions.setSession('session-1', [])
    const { result } = renderHook(() =>
      useRunSSE({
        tenantId: 'tenant-1',
        sessionId: 'session-1',
        delayMs: async (ms) => void delays.push(ms),
      }),
    )

    await act(async () => result.current.sendPrompt('go'))

    expect(vi.mocked(runApi.fetchRunEvents).mock.calls[1][2]?.lastEventId).toBe(
      'v1:7:99-3',
    )
    expect(delays).toEqual([100])
    expect(snapshot(currentChatState).messages.at(-1)?.content).toBe('AB')
  })

  it('continues a server-discovered active Run after a full remount', async () => {
    vi.mocked(runApi.fetchRunEvents).mockResolvedValue(chunkedSse([
      'id: v1:9:2-0\nevent: token\ndata: {"content":"continued"}\n\n',
      'id: v1:10:2-1\nevent: run.completed\ndata: {}\n\n',
    ]))
    currentChatActions.reset()
    const { result } = renderHook(() => useRunSSE({
      tenantId: 'tenant-1', sessionId: 'session-1',
      initialRunId: 'run-1', initialRunStatus: 'running',
    }))
    await waitFor(() => expect(runApi.fetchRunEvents).toHaveBeenCalled())
    await waitFor(() => expect(result.current.activeRunId).toBeNull())
    expect(runApi.createRun).not.toHaveBeenCalled()
    expect(runApi.fetchRunEvents).toHaveBeenCalledWith('tenant-1', 'run-1', expect.objectContaining({ lastEventId: null }))
    expect(snapshot(currentChatState).messages.at(-1)?.content).toBe('Hello durable')
  })

  it('atomically drops Session A transport state before Session B with no active Run', async () => {
    vi.mocked(runApi.fetchRunEvents)
      .mockImplementationOnce(() => new Promise<Response>(() => {}))
      .mockResolvedValueOnce(chunkedSse([]))
    vi.mocked(runApi.createRun).mockResolvedValue(run('queued', 'run-b'))
    vi.mocked(runApi.getRun).mockResolvedValue(run('completed', 'run-b'))
    const { result, rerender } = renderHook(
      (props: { sessionId: string; runId: string | null; status: RunResponse['status'] | null }) =>
        useRunSSE({
          tenantId: 'tenant-1', sessionId: props.sessionId,
          initialRunId: props.runId, initialRunStatus: props.status,
        }),
      { initialProps: { sessionId: 'session-a', runId: 'run-a', status: 'running' } },
    )
    await waitFor(() => expect(result.current.activeRunId).toBe('run-a'))
    currentChatActions.setLastEventId('a-cursor')

    rerender({ sessionId: 'session-b', runId: null, status: null })
    await waitFor(() => expect(result.current.activeRunId).toBeNull())
    expect(result.current.status).toBe('idle')
    expect(result.current.pause).toBeNull()
    expect(snapshot(currentChatState).last_event_id).toBeNull()

    await act(async () => result.current.sendPrompt('for B'))
    expect(runApi.createRun).toHaveBeenLastCalledWith(
      'tenant-1',
      expect.objectContaining({ session_id: 'session-b', prompt: 'for B' }),
      expect.any(String), expect.any(Function), expect.any(AbortSignal),
    )
  })

  it('replaces Session A active transport with Session B initial active Run', async () => {
    vi.mocked(runApi.fetchRunEvents).mockImplementation(() => new Promise<Response>(() => {}))
    const { result, rerender } = renderHook(
      (props: { sessionId: string; runId: string }) => useRunSSE({
        tenantId: 'tenant-1', sessionId: props.sessionId,
        initialRunId: props.runId, initialRunStatus: 'running',
      }),
      { initialProps: { sessionId: 'session-a', runId: 'run-a' } },
    )
    await waitFor(() => expect(runApi.fetchRunEvents).toHaveBeenCalledWith(
      'tenant-1', 'run-a', expect.any(Object),
    ))

    rerender({ sessionId: 'session-b', runId: 'run-b' })
    await waitFor(() => expect(runApi.fetchRunEvents).toHaveBeenCalledWith(
      'tenant-1', 'run-b', expect.any(Object),
    ))
    expect(result.current.activeRunId).toBe('run-b')
    expect(result.current.status).toBe('running')
  })

  it('keeps durable initial pause when run.paused arrives before Redis request events', async () => {
    vi.mocked(runApi.fetchRunEvents).mockResolvedValue(chunkedSse([
      'id: v1:5:0-0\nevent: run.paused\ndata: {}\n\n',
    ]))
    vi.mocked(runApi.getRun).mockResolvedValue(run('waiting_input'))
    const initialPause = { type: 'input_request' as const, request: { question: '成本价？' } }
    const { result } = renderHook(() => useRunSSE({
      tenantId: 'tenant-1', sessionId: 'session-1', initialRunId: 'run-1',
      initialRunStatus: 'waiting_input', initialPause,
    }))
    await waitFor(() => expect(runApi.fetchRunEvents).toHaveBeenCalled())
    expect(result.current.pause).toEqual(initialPause)
  })

  it('blocks interleaving and consumes a cancelled Run once as the next prompt revision base', async () => {
    let releaseStream!: () => void
    vi.mocked(runApi.fetchRunEvents).mockImplementation(
      () => new Promise<Response>((resolve) => {
        releaseStream = () => resolve(chunkedSse([]))
      }),
    )
    vi.mocked(runApi.cancelRun).mockResolvedValue(run('cancelled'))
    currentChatActions.setSession('session-1', [])
    const { result } = renderHook(() =>
      useRunSSE({ tenantId: 'tenant-1', sessionId: 'session-1' }),
    )

    let first!: Promise<void>
    act(() => {
      first = result.current.sendPrompt('first')
    })
    await waitFor(() => expect(result.current.activeRunId).toBe('run-1'))
    await act(async () => result.current.sendPrompt('interleave'))
    expect(runApi.createRun).toHaveBeenCalledTimes(1)

    await act(async () => result.current.cancelRun())
    expect(runApi.cancelRun).toHaveBeenCalledWith(
      'tenant-1',
      'run-1',
      expect.any(Function),
    )
    releaseStream()
    await first.catch(() => {})

    vi.mocked(runApi.createRun).mockResolvedValue(run('queued', 'run-2'))
    vi.mocked(runApi.fetchRunEvents).mockResolvedValue(chunkedSse([]))
    await act(async () => result.current.sendPrompt('edited'))
    expect(runApi.createRun).toHaveBeenLastCalledWith(
      'tenant-1',
      expect.objectContaining({ prompt: 'edited', replaces_run_id: 'run-1' }),
      expect.any(String),
      expect.any(Function),
      expect.any(AbortSignal),
    )

    vi.mocked(runApi.createRun).mockResolvedValue(run('queued', 'run-3'))
    await act(async () => result.current.sendPrompt('normal next turn'))
    expect(runApi.createRun).toHaveBeenLastCalledWith(
      'tenant-1',
      expect.not.objectContaining({ replaces_run_id: expect.anything() }),
      expect.any(String),
      expect.any(Function),
      expect.any(AbortSignal),
    )
  })

  it('serializes a pending create so a double send cannot POST twice', async () => {
    let resolveCreate!: (value: RunResponse) => void
    vi.mocked(runApi.createRun).mockImplementation(
      () => new Promise<RunResponse>((resolve) => { resolveCreate = resolve }),
    )
    vi.mocked(runApi.fetchRunEvents).mockResolvedValue(chunkedSse([]))
    vi.mocked(runApi.getRun).mockResolvedValue(run('completed'))
    const { result } = renderHook(() =>
      useRunSSE({ tenantId: 'tenant-1', sessionId: 'session-1' }),
    )

    let first!: Promise<void>
    act(() => {
      first = result.current.sendPrompt('same prompt')
      void result.current.sendPrompt('same prompt')
    })
    expect(runApi.createRun).toHaveBeenCalledTimes(1)
    resolveCreate(run('queued'))
    await act(async () => first)
  })

  it('replays an uncertain create with the exact same body and idempotency key', async () => {
    vi.mocked(runApi.createRun)
      .mockRejectedValueOnce(new TypeError('response lost'))
      .mockResolvedValueOnce(run('queued'))
    vi.mocked(runApi.fetchRunEvents).mockResolvedValue(chunkedSse([]))
    vi.mocked(runApi.getRun).mockResolvedValue(run('completed'))
    const delays: number[] = []
    const { result } = renderHook(() => useRunSSE({
      tenantId: 'tenant-1', sessionId: 'session-1',
      delayMs: async (ms) => { delays.push(ms) },
    }))

    await act(async () => result.current.sendPrompt('replay me'))

    expect(runApi.createRun).toHaveBeenCalledTimes(2)
    expect(vi.mocked(runApi.createRun).mock.calls[1].slice(0, 3)).toEqual(
      vi.mocked(runApi.createRun).mock.calls[0].slice(0, 3),
    )
    expect(delays).toEqual([100])
  })

  it('records Stop during create and server-cancels immediately after the Run id arrives', async () => {
    let resolveCreate!: (value: RunResponse) => void
    vi.mocked(runApi.createRun).mockImplementation(
      () => new Promise<RunResponse>((resolve) => { resolveCreate = resolve }),
    )
    vi.mocked(runApi.cancelRun).mockResolvedValue(run('cancelled'))
    const { result } = renderHook(() =>
      useRunSSE({ tenantId: 'tenant-1', sessionId: 'session-1' }),
    )

    let started!: Promise<void>
    act(() => { started = result.current.sendPrompt('stop while posting') })
    await waitFor(() => expect(runApi.createRun).toHaveBeenCalledTimes(1))
    await act(async () => result.current.cancelRun())
    expect(runApi.cancelRun).not.toHaveBeenCalled()
    resolveCreate(run('queued'))
    await act(async () => started)

    expect(runApi.cancelRun).toHaveBeenCalledWith('tenant-1', 'run-1', expect.any(Function))
    expect(result.current.activeRunId).toBeNull()
    expect(result.current.status).toBe('cancelled')
  })

  it('preserves approval/input pause requests, blocks ordinary send and resumes with typed responses', async () => {
    vi.mocked(runApi.fetchRunEvents).mockResolvedValue(chunkedSse([
      'id: v1:1:1-0\nevent: approval_request\ndata: {"tool":"trade"}\n\n',
      'id: v1:2:1-1\nevent: run.paused\ndata: {}\n\n',
    ]))
    vi.mocked(runApi.getRun).mockResolvedValue(run('waiting_approval'))
    vi.mocked(runApi.resumeRun).mockResolvedValue(run('queued'))
    currentChatActions.setSession('session-1', [])
    const { result } = renderHook(() => useRunSSE({ tenantId: 'tenant-1', sessionId: 'session-1' }))

    await act(async () => result.current.sendPrompt('trade'))
    expect(result.current.pause).toEqual({ type: 'approval_request', request: { tool: 'trade' } })
    await act(async () => result.current.sendPrompt('must block'))
    expect(runApi.createRun).toHaveBeenCalledTimes(1)
    vi.mocked(runApi.resumeRun).mockRejectedValueOnce(new TypeError('resume offline'))
    await expect(act(async () => result.current.resumeRun({ approved: true }))).resolves.toBeUndefined()
    expect(result.current.pause).not.toBeNull()

    vi.mocked(runApi.fetchRunEvents).mockResolvedValue(chunkedSse([]))
    vi.mocked(runApi.resumeRun).mockResolvedValue(run('queued'))
    vi.mocked(runApi.getRun).mockResolvedValue(run('completed'))
    await act(async () => result.current.resumeRun({ approved: false }))
    expect(runApi.resumeRun).toHaveBeenCalledWith('tenant-1', 'run-1', { approved: false }, expect.any(Function))
    expect(result.current.pause).toBeNull()
  })

  it('contains unresolved-tenant and network failures without rejected UI promises', async () => {
    const noTenant = renderHook(() => useRunSSE({ tenantId: null, sessionId: null }))
    await expect(act(async () => noTenant.result.current.sendPrompt('early'))).resolves.toBeUndefined()
    expect(noTenant.result.current.status).toBe('error')

    vi.mocked(runApi.createRun).mockRejectedValue(new TypeError('offline'))
    const created = renderHook(() => useRunSSE({ tenantId: 'tenant-1', sessionId: 'session-1' }))
    await expect(act(async () => created.result.current.sendPrompt('offline'))).resolves.toBeUndefined()
    expect(created.result.current.status).toBe('error')

    let release!: () => void
    vi.mocked(runApi.createRun).mockResolvedValue(run('queued'))
    vi.mocked(runApi.fetchRunEvents).mockImplementation(() => new Promise((resolve) => {
      release = () => resolve(chunkedSse([]))
    }))
    vi.mocked(runApi.cancelRun).mockRejectedValue(new TypeError('cancel offline'))
    const cancelling = renderHook(() => useRunSSE({ tenantId: 'tenant-1', sessionId: 'session-1' }))
    let started!: Promise<void>
    act(() => { started = cancelling.result.current.sendPrompt('start') })
    await waitFor(() => expect(cancelling.result.current.activeRunId).toBe('run-1'))
    await expect(act(async () => cancelling.result.current.cancelRun())).resolves.toBeUndefined()
    expect(cancelling.result.current.status).toBe('error')
    expect(snapshot(currentChatState).active_run_id).toBe('run-1')
    const createsBeforeBlockedSend = vi.mocked(runApi.createRun).mock.calls.length
    await act(async () => cancelling.result.current.sendPrompt('must remain blocked'))
    expect(runApi.createRun).toHaveBeenCalledTimes(createsBeforeBlockedSend)
    vi.mocked(runApi.cancelRun).mockResolvedValue(run('cancelled'))
    await act(async () => cancelling.result.current.cancelRun())
    expect(runApi.cancelRun).toHaveBeenCalledTimes(2)
    release()
    await started
  })

  it('exhausts reconnect attempts without inventing a failed Run or losing cancel control', async () => {
    vi.mocked(runApi.fetchRunEvents).mockRejectedValue(new TypeError('network down'))
    vi.mocked(runApi.getRun).mockResolvedValue(run('running'))
    vi.mocked(runApi.cancelRun).mockResolvedValue(run('cancelled'))
    const delays: number[] = []
    currentChatActions.setSession('session-1', [])
    const { result, unmount } = renderHook(() =>
      useRunSSE({
        tenantId: 'tenant-1',
        sessionId: 'session-1',
        maxReconnectAttempts: 3,
        delayMs: async (ms) => void delays.push(ms),
      }),
    )
    await act(async () => result.current.sendPrompt('go'))
    expect(runApi.fetchRunEvents).toHaveBeenCalledTimes(4)
    expect(delays).toEqual([100, 200, 400])
    expect(snapshot(currentChatState).streamingStatus).toBe('error')
    expect(snapshot(currentChatState).active_run_status).toBe('running')
    expect(result.current.activeRunId).toBe('run-1')
    expect(result.current.status).toBe('running')

    await act(async () => result.current.sendPrompt('must remain blocked'))
    expect(runApi.createRun).toHaveBeenCalledTimes(1)
    await act(async () => result.current.cancelRun())
    expect(runApi.cancelRun).toHaveBeenCalledWith('tenant-1', 'run-1', expect.any(Function))

    currentChatActions.reset()
    unmount()
    await Promise.resolve()
    expect(snapshot(currentChatState).messages).toEqual([])
  })

  it('trusts a durable terminal frame when GET calibration fails and permits the next send', async () => {
    vi.mocked(runApi.fetchRunEvents)
      .mockResolvedValueOnce(chunkedSse([
        'id: v1:1:1-0\nevent: run.completed\ndata: {"content":"durable terminal"}\n\n',
      ]))
      .mockResolvedValueOnce(chunkedSse([]))
    vi.mocked(runApi.getRun)
      .mockRejectedValueOnce(new TypeError('GET unavailable'))
      .mockResolvedValueOnce(run('completed', 'run-2'))
    vi.mocked(runApi.createRun)
      .mockResolvedValueOnce(run('queued'))
      .mockResolvedValueOnce(run('queued', 'run-2'))
    const { result } = renderHook(() =>
      useRunSSE({ tenantId: 'tenant-1', sessionId: 'session-1' }),
    )

    await act(async () => result.current.sendPrompt('first'))
    expect(result.current.activeRunId).toBeNull()
    expect(result.current.status).toBe('completed')

    await act(async () => result.current.sendPrompt('second'))
    expect(runApi.createRun).toHaveBeenCalledTimes(2)
  })
})
