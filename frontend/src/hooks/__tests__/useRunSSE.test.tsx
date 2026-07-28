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
    active_pause_id: null,
    active_pause_type: null,
    active_pause_request: null,
    revisions: [],
    revisions_has_more: false,
    revisions_next_cursor: null,
    latest_run_id: null,
    latest_run_status: null,
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

  it('keeps completed status while exposing an action-required terminal outcome', async () => {
    vi.mocked(runApi.fetchRunEvents).mockResolvedValue(chunkedSse([
      'id: v1:2:1-1\nevent: run.completed\ndata: {"content":"先开通权限",' +
        '"outcome":{"code":"action_required","action_type":"apply_market_permission",' +
        '"action_url":"/market-permissions/star/apply","action_label":"申请科创板权限",' +
        '"resume_hint":"完成后返回","intent_summary":"买入中芯国际 100 股"}}\n\n',
    ]))
    const { result } = renderHook(() => useRunSSE({
      tenantId: 'tenant-1', sessionId: 'session-1',
    }))

    await act(async () => result.current.sendPrompt('买入中芯国际'))

    await waitFor(() => {
      expect(result.current.status).toBe('completed')
      expect(result.current.activeRunId).toBeNull()
      expect(result.current.pause).toBeNull()
      expect(result.current.outcome).toEqual(expect.objectContaining({
        code: 'action_required', action_url: '/market-permissions/star/apply',
      }))
    })
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
    const initialPause = { id: 'pause-input', type: 'input_request' as const, request: { question: '成本价？' } }
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
      'id: v1:2:1-1\nevent: run.paused\ndata: {"pause_id":"pause-1","pause_type":"approval","request":{"tool":"trade"}}\n\n',
    ]))
    vi.mocked(runApi.getRun).mockResolvedValue(run('waiting_approval'))
    vi.mocked(runApi.resumeRun).mockResolvedValue(run('queued'))
    currentChatActions.setSession('session-1', [])
    const { result } = renderHook(() => useRunSSE({ tenantId: 'tenant-1', sessionId: 'session-1' }))

    await act(async () => result.current.sendPrompt('trade'))
    expect(result.current.pause).toEqual({ id: 'pause-1', type: 'approval_request', request: { tool: 'trade' } })
    await act(async () => result.current.sendPrompt('must block'))
    expect(runApi.createRun).toHaveBeenCalledTimes(1)
    vi.mocked(runApi.resumeRun).mockRejectedValueOnce(new TypeError('resume offline'))
    await expect(act(async () => result.current.resumeRun({ approved: true }))).resolves.toEqual(
      expect.objectContaining({ ok: false }),
    )
    expect(result.current.pause).not.toBeNull()

    vi.mocked(runApi.fetchRunEvents).mockResolvedValue(chunkedSse([]))
    vi.mocked(runApi.resumeRun).mockResolvedValue(run('queued'))
    vi.mocked(runApi.getRun).mockResolvedValue(run('completed'))
    await act(async () => result.current.resumeRun({ approved: false }))
    expect(runApi.resumeRun).toHaveBeenCalledWith('tenant-1', 'run-1', 'pause-1', { approved: false }, expect.any(Function))
    expect(result.current.pause).toBeNull()
  })

  it('forwards closed editable approval responses without rewriting Decimal strings', async () => {
    vi.mocked(runApi.getRun).mockResolvedValue(run('waiting_approval'))
    vi.mocked(runApi.fetchRunEvents).mockResolvedValue(chunkedSse([
      'id: v1:1:1-0\nevent: run.paused\ndata: {}\n\n',
    ]))
    vi.mocked(runApi.resumeRun).mockImplementation(() => new Promise(() => {}))
    const { result, unmount } = renderHook(() => useRunSSE({
      tenantId: 'tenant-1',
      sessionId: 'session-1',
      initialRunId: 'run-1',
      initialRunStatus: 'waiting_approval',
      initialPause: {
        id: 'pause-trade',
        type: 'approval_request',
        request: {
          tool_calls: [{
            id: 'trade-1',
            name: 'place_paper_order',
            arguments: '{"quantity":100,"limit_price":"1500.0000"}',
          }],
          editable_tool_call_ids: ['trade-1'],
        },
      },
      delayMs: async () => {},
    }))
    await waitFor(() => expect(result.current.activeRunId).toBe('run-1'))

    act(() => {
      void result.current.resumeRun({
        approved: true,
        edited_arguments: {
          'trade-1': { quantity: 200, limit_price: '1498.5000' },
        },
      })
    })

    expect(runApi.resumeRun).toHaveBeenCalledWith(
      'tenant-1',
      'run-1',
      'pause-trade',
      {
        approved: true,
        edited_arguments: {
          'trade-1': { quantity: 200, limit_price: '1498.5000' },
        },
      },
      expect.any(Function),
    )
    unmount()
  })

  it('uses one cancel/resume fence and calibrates durable facts after an uncertain resume', async () => {
    let rejectResume!: (reason: unknown) => void
    vi.mocked(runApi.resumeRun).mockImplementation(
      () => new Promise<RunResponse>((_resolve, reject) => { rejectResume = reject }),
    )
    vi.mocked(runApi.getRunSession).mockResolvedValue({
      ...detail(), active_run_id: 'run-1', active_run_status: 'waiting_input',
      active_pause_id: 'pause-input',
      active_pause_type: 'input', active_pause_request: { question: 'still waiting' },
    })
    vi.mocked(runApi.getRun).mockResolvedValue(run('waiting_input'))
    const initialPause = { id: 'pause-approval', type: 'approval_request' as const, request: { tool: 'trade' } }
    const { result } = renderHook(() => useRunSSE({
      tenantId: 'tenant-1', sessionId: 'session-1', initialRunId: 'run-1',
      initialRunStatus: 'waiting_approval', initialPause,
    }))
    await waitFor(() => expect(result.current.activeRunId).toBe('run-1'))

    let first!: Promise<{ ok: boolean }>
    act(() => {
      first = result.current.resumeRun({ approved: true })
      void result.current.resumeRun({ approved: false })
      void result.current.cancelRun()
    })
    expect(result.current.commandPending).toBe(true)
    expect(runApi.resumeRun).toHaveBeenCalledTimes(1)
    expect(runApi.cancelRun).not.toHaveBeenCalled()
    rejectResume(new TypeError('response lost'))
    await act(async () => expect(first).resolves.toEqual(expect.objectContaining({ ok: false })))

    expect(runApi.getRunSession).toHaveBeenCalled()
    expect(runApi.getRun).not.toHaveBeenCalled()
    expect(result.current.pause).toEqual({
      id: 'pause-input',
      type: 'input_request', request: { question: 'still waiting' },
    })
    expect(result.current.status).toBe('waiting_input')
    expect(result.current.commandPending).toBe(false)
  })

  it('keeps the current pause actionable when another tab submits a stale pause identity', async () => {
    vi.mocked(runApi.fetchRunEvents)
      .mockImplementationOnce((_tenantId, _runId, options) =>
        new Promise<Response>((_resolve, reject) => {
          options.signal?.addEventListener(
            'abort',
            () => reject(new DOMException('aborted', 'AbortError')),
            { once: true },
          )
        }),
      )
      .mockResolvedValue(chunkedSse([]))
    vi.mocked(runApi.getRun).mockResolvedValue(run('waiting_approval'))
    vi.mocked(runApi.getRunSession).mockResolvedValue({
      ...detail(),
      active_run_id: 'run-1',
      active_run_status: 'waiting_approval',
      active_pause_id: 'pause-2',
      active_pause_type: 'approval',
      active_pause_request: { action: 'second approval' },
    })
    vi.mocked(runApi.resumeRun).mockImplementation(
      async (_tenantId, _runId, pauseId) => {
        if (pauseId === 'pause-1') throw new Error('POST resume failed: 409')
        return run('queued')
      },
    )
    const noDelay = async () => {}
    const tabA = renderHook(() => useRunSSE({
      tenantId: 'tenant-1',
      sessionId: 'session-1',
      initialRunId: 'run-1',
      initialRunStatus: 'waiting_approval',
      initialPause: {
        id: 'pause-1',
        type: 'approval_request',
        request: { action: 'first approval' },
      },
      delayMs: noDelay,
      maxReconnectAttempts: 0,
    }))
    const tabB = renderHook(() => useRunSSE({
      tenantId: 'tenant-1',
      sessionId: 'session-1',
      initialRunId: 'run-1',
      initialRunStatus: 'waiting_approval',
      initialPause: {
        id: 'pause-2',
        type: 'approval_request',
        request: { action: 'second approval' },
      },
      delayMs: noDelay,
      maxReconnectAttempts: 0,
    }))
    await waitFor(() => expect(tabA.result.current.activeRunId).toBe('run-1'))
    await waitFor(() => expect(tabB.result.current.activeRunId).toBe('run-1'))

    await act(async () => {
      await tabA.result.current.resumeRun({ approved: true })
    })

    expect(runApi.resumeRun).toHaveBeenCalledWith(
      'tenant-1',
      'run-1',
      'pause-1',
      { approved: true },
      expect.any(Function),
    )
    expect(tabA.result.current.status).toBe('waiting_approval')
    expect(tabA.result.current.pause).toEqual({
      id: 'pause-2',
      type: 'approval_request',
      request: { action: 'second approval' },
    })
    expect(tabB.result.current.pause).toEqual({
      id: 'pause-2',
      type: 'approval_request',
      request: { action: 'second approval' },
    })
  })

  it('recovers pause two when a delayed successful resume misses the next pause event', async () => {
    let resolveResume!: (value: RunResponse) => void
    vi.mocked(runApi.resumeRun).mockImplementation(
      () => new Promise<RunResponse>((resolve) => { resolveResume = resolve }),
    )
    vi.mocked(runApi.fetchRunEvents)
      .mockImplementationOnce((_tenantId, _runId, options) =>
        new Promise<Response>((_resolve, reject) => {
          options.signal?.addEventListener(
            'abort',
            () => reject(new DOMException('aborted', 'AbortError')),
            { once: true },
          )
        }),
      )
      .mockResolvedValue(chunkedSse([]))
    vi.mocked(runApi.getRun).mockResolvedValue(run('queued'))
    vi.mocked(runApi.getRunSession).mockResolvedValue({
      ...detail(),
      active_run_id: 'run-1',
      active_run_status: 'waiting_approval',
      active_pause_id: 'pause-2',
      active_pause_type: 'approval',
      active_pause_request: { action: 'second approval' },
    })
    const { result } = renderHook(() => useRunSSE({
      tenantId: 'tenant-1',
      sessionId: 'session-1',
      initialRunId: 'run-1',
      initialRunStatus: 'waiting_approval',
      initialPause: {
        id: 'pause-1',
        type: 'approval_request',
        request: { action: 'first approval' },
      },
      maxReconnectAttempts: 0,
    }))
    await waitFor(() => expect(result.current.activeRunId).toBe('run-1'))

    let resume!: Promise<{ ok: boolean }>
    act(() => {
      resume = result.current.resumeRun({ approved: true })
    })
    await waitFor(() => expect(runApi.resumeRun).toHaveBeenCalledWith(
      'tenant-1',
      'run-1',
      'pause-1',
      { approved: true },
      expect.any(Function),
    ))
    resolveResume(run('queued'))
    await act(async () => {
      await resume
    })

    expect(runApi.getRunSession).toHaveBeenCalled()
    expect(result.current.status).toBe('waiting_approval')
    expect(result.current.pause).toEqual({
      id: 'pause-2',
      type: 'approval_request',
      request: { action: 'second approval' },
    })
  })

  it('does not wait for or combine an older Run read with a newer Session pause snapshot', async () => {
    vi.mocked(runApi.getRun).mockImplementation(() => new Promise<RunResponse>(() => undefined))
    vi.mocked(runApi.getRunSession).mockResolvedValue({
      ...detail(),
      active_run_id: 'run-1',
      active_run_status: 'waiting_approval',
      active_pause_id: 'pause-2',
      active_pause_type: 'approval',
      active_pause_request: { action: 'second approval' },
      latest_run_id: 'run-1',
      latest_run_status: 'waiting_approval',
    })
    vi.mocked(runApi.fetchRunEvents).mockResolvedValue(chunkedSse([]))

    const { result } = renderHook(() => useRunSSE({
      tenantId: 'tenant-1',
      sessionId: 'session-1',
      initialRunId: 'run-1',
      initialRunStatus: 'queued',
      maxReconnectAttempts: 0,
    }))

    await waitFor(() => expect(result.current.pause?.id).toBe('pause-2'))
    expect(runApi.getRun).not.toHaveBeenCalled()
    expect(result.current.status).toBe('waiting_approval')
  })

  it('does not resurrect an old pause while a newer Session snapshot is deferred', async () => {
    let resolveSession!: (value: RunSessionDetail) => void
    vi.mocked(runApi.getRun).mockResolvedValue(run('waiting_approval'))
    vi.mocked(runApi.getRunSession).mockImplementation(
      () => new Promise<RunSessionDetail>((resolve) => { resolveSession = resolve }),
    )
    vi.mocked(runApi.fetchRunEvents).mockResolvedValue(chunkedSse([]))
    const { result } = renderHook(() => useRunSSE({
      tenantId: 'tenant-1',
      sessionId: 'session-1',
      initialRunId: 'run-1',
      initialRunStatus: 'waiting_approval',
      initialPause: {
        id: 'pause-old',
        type: 'approval_request',
        request: { action: 'old approval' },
      },
      maxReconnectAttempts: 0,
    }))
    await waitFor(() => expect(runApi.getRunSession).toHaveBeenCalled())

    act(() => resolveSession({
      ...detail(),
      active_run_id: 'run-1',
      active_run_status: 'running',
      latest_run_id: 'run-1',
      latest_run_status: 'running',
    }))

    await waitFor(() => expect(result.current.status).toBe('running'))
    expect(result.current.pause).toBeNull()
    expect(runApi.getRun).not.toHaveBeenCalled()
  })

  it('does not let an old terminal Run clear a newer active Run and pause', async () => {
    let resolveSession!: (value: RunSessionDetail) => void
    vi.mocked(runApi.getRun).mockResolvedValue(run('completed', 'run-1'))
    vi.mocked(runApi.getRunSession).mockImplementation(
      () => new Promise<RunSessionDetail>((resolve) => { resolveSession = resolve }),
    )
    vi.mocked(runApi.fetchRunEvents).mockResolvedValue(chunkedSse([]))
    const { result } = renderHook(() => useRunSSE({
      tenantId: 'tenant-1',
      sessionId: 'session-1',
      initialRunId: 'run-1',
      initialRunStatus: 'running',
      maxReconnectAttempts: 0,
    }))
    await waitFor(() => expect(runApi.getRunSession).toHaveBeenCalled())

    act(() => resolveSession({
      ...detail(),
      active_run_id: 'run-2',
      active_run_status: 'waiting_input',
      active_pause_id: 'pause-2',
      active_pause_type: 'input',
      active_pause_request: { question: 'new input' },
      latest_run_id: 'run-2',
      latest_run_status: 'waiting_input',
    }))

    await waitFor(() => expect(result.current.activeRunId).toBe('run-2'))
    expect(result.current.status).toBe('waiting_input')
    expect(result.current.pause).toEqual({
      id: 'pause-2',
      type: 'input_request',
      request: { question: 'new input' },
    })
    expect(runApi.getRun).not.toHaveBeenCalled()
  })

  it('hands one stream owner from run one to a newer running run and consumes its events', async () => {
    let resolveHandoff!: (value: RunSessionDetail) => void
    const appendToken = vi.spyOn(currentChatActions, 'appendRunToken')
    vi.mocked(runApi.fetchRunEvents)
      .mockResolvedValueOnce(chunkedSse([]))
      .mockResolvedValueOnce(chunkedSse([
        'id: v2:1:1-0\nevent: token\ndata: {"content":"handoff token"}\n\n',
        'id: v2:2:1-1\nevent: run.completed\ndata: {"content":"run two done"}\n\n',
      ]))
    vi.mocked(runApi.getRunSession)
      .mockImplementationOnce(
        () => new Promise<RunSessionDetail>((resolve) => { resolveHandoff = resolve }),
      )
      .mockResolvedValue({
        ...detail('run two done'),
        latest_run_id: 'run-2',
        latest_run_status: 'completed',
      })
    const { result } = renderHook(() => useRunSSE({
      tenantId: 'tenant-1',
      sessionId: 'session-1',
      initialRunId: 'run-1',
      initialRunStatus: 'running',
      maxReconnectAttempts: 0,
    }))
    await waitFor(() => expect(runApi.getRunSession).toHaveBeenCalledTimes(1))

    act(() => resolveHandoff({
      ...detail(),
      active_run_id: 'run-2',
      active_run_status: 'running',
      latest_run_id: 'run-2',
      latest_run_status: 'running',
    }))

    await waitFor(() => expect(runApi.fetchRunEvents).toHaveBeenCalledWith(
      'tenant-1',
      'run-2',
      expect.objectContaining({ lastEventId: null }),
    ))
    await waitFor(() => expect(result.current.status).toBe('completed'))
    expect(appendToken).toHaveBeenCalledWith('handoff token')
    expect(result.current.activeRunId).toBeNull()
    expect(runApi.fetchRunEvents).toHaveBeenCalledTimes(2)
  })

  it('consumes a pause event after handing the stream to a newer run', async () => {
    let resolveHandoff!: (value: RunSessionDetail) => void
    vi.mocked(runApi.fetchRunEvents)
      .mockResolvedValueOnce(chunkedSse([]))
      .mockResolvedValueOnce(chunkedSse([
        'id: v2:1:1-0\nevent: run.paused\ndata: {"pause_id":"pause-2","pause_type":"input","request":{"question":"run two input"}}\n\n',
      ]))
    vi.mocked(runApi.getRunSession)
      .mockImplementationOnce(
        () => new Promise<RunSessionDetail>((resolve) => { resolveHandoff = resolve }),
      )
      .mockRejectedValueOnce(new TypeError('snapshot temporarily unavailable'))
    vi.mocked(runApi.getRun).mockResolvedValue(run('waiting_input', 'run-2'))
    const { result } = renderHook(() => useRunSSE({
      tenantId: 'tenant-1',
      sessionId: 'session-1',
      initialRunId: 'run-1',
      initialRunStatus: 'running',
      maxReconnectAttempts: 0,
    }))
    await waitFor(() => expect(runApi.getRunSession).toHaveBeenCalledTimes(1))

    act(() => resolveHandoff({
      ...detail(),
      active_run_id: 'run-2',
      active_run_status: 'running',
      latest_run_id: 'run-2',
      latest_run_status: 'running',
    }))

    await waitFor(() => expect(result.current.pause?.id).toBe('pause-2'))
    expect(result.current.activeRunId).toBe('run-2')
    expect(result.current.status).toBe('waiting_input')
    expect(runApi.fetchRunEvents).toHaveBeenCalledTimes(2)
    expect(runApi.getRun).toHaveBeenCalledWith('tenant-1', 'run-2', expect.any(Function))
  })

  it('still calibrates Run truth when Session calibration is unavailable', async () => {
    vi.mocked(runApi.cancelRun).mockRejectedValue(new TypeError('timeout'))
    vi.mocked(runApi.getRunSession).mockRejectedValue(new TypeError('session unavailable'))
    vi.mocked(runApi.getRun).mockResolvedValue(run('running'))
    const { result } = renderHook(() => useRunSSE({
      tenantId: 'tenant-1', sessionId: 'session-1', initialRunId: 'run-1',
      initialRunStatus: 'running',
    }))
    await waitFor(() => expect(result.current.activeRunId).toBe('run-1'))
    await act(async () => { await result.current.cancelRun() })
    expect(runApi.getRun).toHaveBeenCalledWith('tenant-1', 'run-1', expect.any(Function))
    expect(result.current.status).toBe('running')
    expect(result.current.activeRunId).toBe('run-1')
  })

  it.each(['queued', 'completed'] as const)(
    'clears a stale pause from %s Run truth even when Session calibration fails',
    async (durableStatus) => {
      const initialPause = { id: 'pause-approval', type: 'approval_request' as const, request: { tool: 'trade' } }
      vi.mocked(runApi.resumeRun).mockRejectedValue(new TypeError('response lost'))
      vi.mocked(runApi.getRunSession).mockRejectedValue(new TypeError('session unavailable'))
      vi.mocked(runApi.getRun).mockResolvedValue(run(durableStatus))
      const { result } = renderHook(() => useRunSSE({
        tenantId: 'tenant-1', sessionId: 'session-1', initialRunId: 'run-1',
        initialRunStatus: 'waiting_approval',
        initialPause,
      }))
      await waitFor(() => expect(result.current.activeRunId).toBe('run-1'))

      await act(async () => { await result.current.resumeRun({ approved: true }) })

      expect(result.current.pause).toBeNull()
      expect(result.current.status).toBe(durableStatus)
    },
  )

  it('releases the resume POST fence before the resumed SSE finishes so Stop remains available', async () => {
    let releaseStream!: () => void
    vi.mocked(runApi.resumeRun).mockResolvedValue(run('queued'))
    vi.mocked(runApi.getRun).mockResolvedValue(run('queued'))
    vi.mocked(runApi.fetchRunEvents).mockImplementation(
      () => new Promise<Response>((resolve) => { releaseStream = () => resolve(chunkedSse([])) }),
    )
    vi.mocked(runApi.cancelRun).mockResolvedValue(run('cancelled'))
    const initialPause = { id: 'pause-approval', type: 'approval_request' as const, request: { tool: 'trade' } }
    const { result } = renderHook(() => useRunSSE({
      tenantId: 'tenant-1', sessionId: 'session-1', initialRunId: 'run-1',
      initialRunStatus: 'waiting_approval',
      initialPause,
    }))
    await waitFor(() => expect(result.current.activeRunId).toBe('run-1'))

    let resume!: Promise<{ ok: boolean }>
    act(() => { resume = result.current.resumeRun({ approved: true }) })
    await waitFor(() => expect(runApi.fetchRunEvents).toHaveBeenCalled())
    await waitFor(() => expect(result.current.commandPending).toBe(false))
    await act(async () => { await result.current.cancelRun() })

    expect(runApi.cancelRun).toHaveBeenCalledWith('tenant-1', 'run-1', expect.any(Function))
    expect(result.current.status).toBe('cancelled')
    releaseStream()
    await resume
    expect(result.current.commandPending).toBe(false)
  })

  it('loads older revision pages with the opaque cursor and prepends without duplicates', async () => {
    const revision = (id: string) => ({
      id, replaces_run_id: null, status: 'completed' as const, prompt: id,
      final_message_summary: null, created_at: '2026-07-18T00:00:00Z', finished_at: null,
    })
    vi.mocked(runApi.getRunSession).mockResolvedValue({
      ...detail(), revisions: [revision('run-1'), revision('run-2')],
      revisions_has_more: false, revisions_next_cursor: null, latest_run_id: 'run-4',
    })
    const { result } = renderHook(() => useRunSSE({
      tenantId: 'tenant-1', sessionId: 'session-1',
      initialRevisions: [revision('run-3'), revision('run-4')],
      initialLatestRunId: 'run-4', initialRevisionCursor: 'opaque-page-2',
      initialRevisionsHasMore: true,
    }))
    await act(async () => { await result.current.loadMoreRevisions() })
    expect(runApi.getRunSession).toHaveBeenCalledWith(
      'tenant-1', 'session-1', expect.any(Function), 'opaque-page-2',
    )
    expect(result.current.revisions.map((item) => item.id)).toEqual([
      'run-1', 'run-2', 'run-3', 'run-4',
    ])
    expect(result.current.revisionsHasMore).toBe(false)
  })

  it('keeps a waiting pause actionable when cancel transport fails and clears it only after terminal cancel', async () => {
    const waitingPause = {
      id: 'pause-input',
      type: 'input_request' as const,
      request: { question: 'Need context' },
    }
    vi.mocked(runApi.fetchRunEvents).mockResolvedValue(chunkedSse([]))
    vi.mocked(runApi.getRun).mockResolvedValue(run('waiting_input'))
    vi.mocked(runApi.cancelRun)
      .mockReset()
      .mockRejectedValueOnce(new TypeError('cancel offline'))
      .mockResolvedValueOnce(run('cancelled'))
    const noDelay = async () => {}
    const { result } = renderHook(() => useRunSSE({
      tenantId: 'tenant-1',
      sessionId: 'session-1',
      initialRunId: 'run-1',
      initialRunStatus: 'waiting_input',
      initialPause: waitingPause,
      delayMs: noDelay,
      maxReconnectAttempts: 0,
    }))
    await waitFor(() => expect(result.current.activeRunId).toBe('run-1'))

    await act(async () => result.current.cancelRun())
    expect(result.current.pause).toEqual(waitingPause)
    expect(result.current.activeRunId).toBe('run-1')

    await act(async () => result.current.cancelRun())
    expect(runApi.cancelRun).toHaveBeenCalledTimes(2)
    expect(result.current.status).toBe('cancelled')
    expect(result.current.activeRunId).toBeNull()
    expect(result.current.pause).toBeNull()
  })

  it('contains unresolved-tenant and network failures without rejected UI promises', async () => {
    const noTenant = renderHook(() => useRunSSE({ tenantId: null, sessionId: null }))
    await expect(act(async () => noTenant.result.current.sendPrompt('early'))).resolves.toEqual(
      expect.objectContaining({ ok: false }),
    )
    expect(noTenant.result.current.status).toBe('error')

    vi.mocked(runApi.createRun).mockRejectedValue(new TypeError('offline'))
    const created = renderHook(() => useRunSSE({ tenantId: 'tenant-1', sessionId: 'session-1' }))
    await expect(act(async () => created.result.current.sendPrompt('offline'))).resolves.toEqual(
      expect.objectContaining({ ok: false }),
    )
    expect(created.result.current.status).toBe('error')

    let release!: () => void
    vi.mocked(runApi.createRun).mockResolvedValue(run('queued'))
    vi.mocked(runApi.fetchRunEvents).mockImplementation(() => new Promise((resolve) => {
      release = () => resolve(chunkedSse([]))
    }))
    vi.mocked(runApi.cancelRun).mockRejectedValue(new TypeError('cancel offline'))
    const initialRevision = {
      id: 'run-1', replaces_run_id: null, status: 'running' as const, prompt: 'start',
      final_message_summary: null, created_at: '2026-07-18T00:00:00Z', finished_at: null,
    }
    vi.mocked(runApi.getRun).mockResolvedValue(run('running'))
    vi.mocked(runApi.getRunSession).mockResolvedValue({
      ...detail(), active_run_id: 'run-1', active_run_status: 'running',
      revisions: [initialRevision], latest_run_id: 'run-1',
    })
    const cancelling = renderHook(() => useRunSSE({
      tenantId: 'tenant-1', sessionId: 'session-1', initialRevisions: [initialRevision],
      initialLatestRunId: 'run-1',
    }))
    let started!: Promise<void>
    act(() => { started = cancelling.result.current.sendPrompt('start') })
    await waitFor(() => expect(cancelling.result.current.activeRunId).toBe('run-1'))
    await expect(act(async () => cancelling.result.current.cancelRun())).resolves.toEqual(
      expect.objectContaining({ ok: false }),
    )
    expect(cancelling.result.current.status).toBe('running')
    expect(cancelling.result.current.revisions).toEqual([initialRevision])
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
