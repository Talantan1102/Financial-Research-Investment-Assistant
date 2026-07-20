import { Route, Routes, useNavigate } from 'react-router-dom'
import { act, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import ChatSessionPage from '@/pages/chat/session'
import { currentChatActions } from '@/store/current-chat'
import { chatSessionsActions } from '@/store/chat-sessions'
import { renderWithProviders } from '@/test-utils/render'
import { server } from '@/test-utils/msw-server'

const API_BASE = (import.meta.env.VITE_API_BASE as string) ?? ''
const now = '2026-07-20T00:00:00Z'

function detail(sessionId: string, runId: string, message: string, withPause = false) {
  return {
    id: sessionId,
    tenant_id: 'tenant-1',
    created_by_user_id: 'user-1',
    title: sessionId,
    created_at: now,
    updated_at: now,
    archived_at: null,
    has_more: false,
    active_run_id: runId,
    active_run_status: 'running',
    active_pause_type: withPause ? 'input' : null,
    active_pause_request: withPause ? { question: 'Session A pause' } : null,
    messages: [
      { id: `message-${sessionId}`, role: 'assistant', content: message, status: 'done', created_at: now },
    ],
  }
}

function run(sessionId: string, runId: string, status: string) {
  return {
    id: runId,
    tenant_id: 'tenant-1',
    session_id: sessionId,
    created_by_user_id: 'user-1',
    run_type: 'chat',
    status,
    replaces_run_id: null,
    retry_count: 0,
    created_at: now,
    queued_at: now,
    finished_at: status === 'cancelled' ? now : null,
    error_code: null,
    error_message: null,
  }
}

function pendingEventStream(): Response {
  return new Response(new ReadableStream<Uint8Array>({ start() {} }), {
    headers: { 'Content-Type': 'text/event-stream' },
  })
}

function RouteHarness() {
  const navigate = useNavigate()
  return (
    <>
      <button type="button" onClick={() => navigate('/chat/session-b')}>Go to B</button>
      <Routes><Route path="/chat/:session_id" element={<ChatSessionPage />} /></Routes>
    </>
  )
}

describe('<ChatSessionPage> route identity integration', () => {
  beforeEach(() => {
    currentChatActions.reset()
    chatSessionsActions.reset()
  })

  it('never restores or cancels Session A Run under Session B while B detail is pending', async () => {
    const user = userEvent.setup()
    let releaseB!: () => void
    const bDetailReleased = new Promise<void>((resolve) => { releaseB = resolve })
    const eventRequests: string[] = []
    const runGets: string[] = []
    const cancels: string[] = []

    server.use(
      http.get(`${API_BASE}/api/v1/tenants`, () => HttpResponse.json([
        { id: 'tenant-1', name: 'Personal', is_personal: true, role: 'owner' },
      ])),
      http.get(`${API_BASE}/api/v1/tenants/tenant-1/sessions/session-a`, () =>
        HttpResponse.json(detail('session-a', 'run-a', 'Session A history', true))),
      http.get(`${API_BASE}/api/v1/tenants/tenant-1/sessions/session-b`, async () => {
        await bDetailReleased
        return HttpResponse.json(detail('session-b', 'run-b', 'Session B history'))
      }),
      http.get(`${API_BASE}/api/v1/tenants/tenant-1/runs/:runId/events`, ({ params }) => {
        const runId = String(params.runId)
        eventRequests.push(runId)
        return pendingEventStream()
      }),
      http.get(`${API_BASE}/api/v1/tenants/tenant-1/runs/:runId`, ({ params }) => {
        const runId = String(params.runId)
        runGets.push(runId)
        return HttpResponse.json(run(runId === 'run-a' ? 'session-a' : 'session-b', runId, 'running'))
      }),
      http.post(`${API_BASE}/api/v1/tenants/tenant-1/runs/:runId/cancel`, ({ params }) => {
        const runId = String(params.runId)
        cancels.push(runId)
        return HttpResponse.json(run(runId === 'run-a' ? 'session-a' : 'session-b', runId, 'cancelled'))
      }),
      http.get(`${API_BASE}/api/v1/tenants/tenant-1/sessions`, () => HttpResponse.json([])),
    )

    renderWithProviders(<RouteHarness />, { initialRoute: '/chat/session-a' })
    expect(await screen.findByText('Session A history')).toBeInTheDocument()
    await waitFor(() => expect(eventRequests).toEqual(['run-a']))

    await user.click(screen.getByRole('button', { name: 'Go to B' }))

    expect(screen.queryByText('Session A history')).not.toBeInTheDocument()
    expect(screen.queryByText('Session A pause')).not.toBeInTheDocument()
    expect(screen.getByTestId('input-textarea')).toBeDisabled()
    await waitFor(() => expect(eventRequests).toEqual(['run-a']))
    expect(runGets).not.toContain('run-a')

    await act(async () => { releaseB() })
    expect(await screen.findByText('Session B history')).toBeInTheDocument()
    await waitFor(() => expect(eventRequests).toEqual(['run-a', 'run-b']))

    await user.keyboard('{Control>}k{/Control}')
    await waitFor(() => expect(cancels).toEqual(['run-b']))
    expect(cancels).not.toContain('run-a')
  })

  it('ignores a Session A detail response that arrives after Session B is current', async () => {
    const user = userEvent.setup()
    let releaseA!: () => void
    const aDetailReleased = new Promise<void>((resolve) => { releaseA = resolve })
    const eventRequests: string[] = []

    server.use(
      http.get(`${API_BASE}/api/v1/tenants`, () => HttpResponse.json([
        { id: 'tenant-1', name: 'Personal', is_personal: true, role: 'owner' },
      ])),
      http.get(`${API_BASE}/api/v1/tenants/tenant-1/sessions/session-a`, async () => {
        await aDetailReleased
        return HttpResponse.json(detail('session-a', 'run-a', 'Late Session A history', true))
      }),
      http.get(`${API_BASE}/api/v1/tenants/tenant-1/sessions/session-b`, () =>
        HttpResponse.json(detail('session-b', 'run-b', 'Current Session B history'))),
      http.get(`${API_BASE}/api/v1/tenants/tenant-1/runs/:runId/events`, ({ params }) => {
        eventRequests.push(String(params.runId))
        return pendingEventStream()
      }),
    )

    renderWithProviders(<RouteHarness />, { initialRoute: '/chat/session-a' })
    await user.click(screen.getByRole('button', { name: 'Go to B' }))
    expect(await screen.findByText('Current Session B history')).toBeInTheDocument()
    await waitFor(() => expect(eventRequests).toEqual(['run-b']))

    await act(async () => { releaseA() })
    await waitFor(() => expect(screen.queryByText('Late Session A history')).not.toBeInTheDocument())
    expect(screen.getByText('Current Session B history')).toBeInTheDocument()
    expect(screen.queryByText('Session A pause')).not.toBeInTheDocument()
    expect(eventRequests).toEqual(['run-b'])
  })
})
