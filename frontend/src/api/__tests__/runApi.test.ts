import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  archiveRunSession,
  cancelRun,
  createRun,
  fetchRunEvents,
  getRun,
  getRunSession,
  listRunSessions,
  listTenants,
  renameRunSession,
  resumeRun,
} from '@/api/runApi'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('runApi', () => {
  beforeEach(() => {
    localStorage.setItem('auth', JSON.stringify({ token: 'run-token' }))
  })

  it('POSTs a Run with bearer auth, Idempotency-Key, nullable session and replacement', async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse({ id: 'run-2', session_id: 'session-1', status: 'queued' }, 201),
    )

    await createRun(
      'tenant-1',
      { session_id: null, prompt: 'edited', replaces_run_id: 'run-1' },
      'idem-1',
      fetchImpl,
    )

    expect(fetchImpl).toHaveBeenCalledTimes(1)
    const [url, init] = fetchImpl.mock.calls[0]
    expect(url).toBe('/api/v1/tenants/tenant-1/runs')
    const headers = new Headers(init?.headers)
    expect(headers.get('Authorization')).toBe('Bearer run-token')
    expect(headers.get('Idempotency-Key')).toBe('idem-1')
    expect(JSON.parse(String(init?.body))).toEqual({
      session_id: null,
      prompt: 'edited',
      replaces_run_id: 'run-1',
    })
  })

  it('passes an AbortSignal to create Run', async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse({ id: 'run-1', session_id: 'session-1', status: 'queued' }, 201),
    )
    const controller = new AbortController()

    await createRun(
      'tenant-1',
      { session_id: 'session-1', prompt: 'signal' },
      'idem-signal',
      fetchImpl,
      controller.signal,
    )

    expect(fetchImpl.mock.calls[0][1]?.signal).toBe(controller.signal)
  })

  it('opens the events stream with Authorization and opaque Last-Event-ID unchanged', async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      new Response('event: token\ndata: {"content":"x"}\n\n', {
        headers: { 'Content-Type': 'text/event-stream' },
      }),
    )
    const cursor = 'v1:17:1735689600000-4'

    await fetchRunEvents('tenant-1', 'run-1', {
      lastEventId: cursor,
      fetchImpl,
    })

    const [url, init] = fetchImpl.mock.calls[0]
    expect(url).toBe('/api/v1/tenants/tenant-1/runs/run-1/events')
    const headers = new Headers(init?.headers)
    expect(headers.get('Authorization')).toBe('Bearer run-token')
    expect(headers.get('Last-Event-ID')).toBe(cursor)
  })

  it('uses only v1 Run control routes for get, cancel and resume', async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockImplementation(async () =>
      jsonResponse({ id: 'run-1', session_id: 'session-1', status: 'queued' }),
    )
    await getRun('tenant-1', 'run-1', fetchImpl)
    await cancelRun('tenant-1', 'run-1', fetchImpl)
    await resumeRun('tenant-1', 'run-1', { approved: true }, fetchImpl)

    expect(fetchImpl.mock.calls.map(([url]) => url)).toEqual([
      '/api/v1/tenants/tenant-1/runs/run-1',
      '/api/v1/tenants/tenant-1/runs/run-1/cancel',
      '/api/v1/tenants/tenant-1/runs/run-1/resume',
    ])
    expect(JSON.parse(String(fetchImpl.mock.calls[2][1]?.body))).toEqual({
      response: { approved: true },
    })
    expect(fetchImpl.mock.calls.some(([url]) => String(url).includes('/steer/'))).toBe(false)
    expect(fetchImpl.mock.calls.some(([url]) => String(url).includes('/retry/'))).toBe(false)
  })

  it('loads tenant sessions and bounded durable detail, then PATCHes title and archives', async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse([{ id: 'tenant-1', is_personal: true }]))
      .mockResolvedValueOnce(jsonResponse([{ id: 'session-1', tenant_id: 'tenant-1' }]))
      .mockResolvedValueOnce(
        jsonResponse({
          id: 'session-1',
          tenant_id: 'tenant-1',
          messages: [],
          has_more: false,
        }),
      )
      .mockResolvedValueOnce(jsonResponse({ id: 'session-1', title: 'Renamed' }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))

    await listTenants(fetchImpl)
    await listRunSessions('tenant-1', fetchImpl)
    await getRunSession('tenant-1', 'session-1', fetchImpl)
    await renameRunSession('tenant-1', 'session-1', 'Renamed', fetchImpl)
    await archiveRunSession('tenant-1', 'session-1', fetchImpl)

    expect(fetchImpl.mock.calls.map(([url]) => url)).toEqual([
      '/api/v1/tenants',
      '/api/v1/tenants/tenant-1/sessions',
      '/api/v1/tenants/tenant-1/sessions/session-1?limit=1000&revision_limit=20',
      '/api/v1/tenants/tenant-1/sessions/session-1',
      '/api/v1/tenants/tenant-1/sessions/session-1',
    ])
    expect(JSON.parse(String(fetchImpl.mock.calls[3][1]?.body))).toEqual({ title: 'Renamed' })
    expect(fetchImpl.mock.calls[4][1]?.method).toBe('DELETE')
  })
})
