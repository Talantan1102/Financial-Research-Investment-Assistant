import { beforeEach, describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test-utils/render'
import { server } from '@/test-utils/msw-server'
import { controllableSseResponse } from '@/test-utils/sse-mock'
import { ChatPane } from '@/components/chat/ChatPane'
import { currentChatActions } from '@/store/current-chat'

const API_BASE = (import.meta.env.VITE_API_BASE as string) ?? ''
const now = '2026-07-18T00:00:00Z'

function run(id: string, status: string) {
  return { id, tenant_id: 'tenant-1', session_id: 'session-1', created_by_user_id: 'user-1',
    run_type: 'chat', status, replaces_run_id: id === 'run-2' ? 'run-1' : null,
    retry_count: 0, created_at: now, queued_at: now, finished_at: status === 'completed' ? now : null,
    error_code: null, error_message: null }
}

describe('<ChatPane> Run revision integration', () => {
  beforeEach(() => {
    currentChatActions.reset()
    currentChatActions.setSession('session-1', [])
  })

  it('routes the first prompt after cancel through one-shot replaces_run_id', async () => {
    const firstStream = controllableSseResponse()
    const bodies: Array<Record<string, unknown>> = []
    let creates = 0
    let sessionRefreshes = 0
    server.use(
      http.post(`${API_BASE}/api/v1/tenants/tenant-1/runs`, async ({ request }) => {
        bodies.push(await request.json() as Record<string, unknown>)
        creates += 1
        return HttpResponse.json(run(`run-${creates}`, 'queued'), { status: 201 })
      }),
      http.get(`${API_BASE}/api/v1/tenants/tenant-1/runs/run-1/events`, () => firstStream.response),
      http.post(`${API_BASE}/api/v1/tenants/tenant-1/runs/run-1/cancel`, () => HttpResponse.json(run('run-1', 'cancelled'))),
      http.get(`${API_BASE}/api/v1/tenants/tenant-1/runs/run-2/events`, () => new Response(
        'id: v1:2:1-0\nevent: run.completed\ndata: {}\n\n',
        { headers: { 'Content-Type': 'text/event-stream' } },
      )),
      http.get(`${API_BASE}/api/v1/tenants/tenant-1/runs/run-2`, () => HttpResponse.json(run('run-2', 'completed'))),
      http.get(`${API_BASE}/api/v1/tenants/tenant-1/sessions/session-1`, () => HttpResponse.json({
        id: 'session-1', tenant_id: 'tenant-1', created_by_user_id: 'user-1', title: 'Session',
        created_at: now, updated_at: now, archived_at: null, messages: [], has_more: false,
        active_run_id: null, active_run_status: null,
        active_pause_type: null, active_pause_request: null,
      })),
      http.get(`${API_BASE}/api/v1/tenants/tenant-1/sessions`, () => {
        sessionRefreshes += 1
        return HttpResponse.json([])
      }),
      http.get(`${API_BASE}/api/v1/tenants`, () => HttpResponse.json([
        { id: 'tenant-1', name: 'Personal', is_personal: true, role: 'owner' },
      ])),
    )

    const user = userEvent.setup()
    const rendered = renderWithProviders(<ChatPane tenantId="tenant-1" sessionId="session-1" />)
    await user.type(rendered.getByTestId('input-textarea'), 'original{Enter}')
    await waitFor(() => expect(rendered.getByRole('button', { name: '停止生成' })).toBeInTheDocument())
    await user.click(rendered.getByRole('button', { name: '停止生成' }))
    await waitFor(() => expect(rendered.getByTestId('input-textarea')).not.toBeDisabled())
    await user.type(rendered.getByTestId('input-textarea'), 'edited{Enter}')
    await waitFor(() => expect(bodies).toHaveLength(2))
    expect(bodies[0]).not.toHaveProperty('replaces_run_id')
    expect(bodies[1]).toMatchObject({ prompt: 'edited', replaces_run_id: 'run-1' })
    await waitFor(() => expect(sessionRefreshes).toBeGreaterThan(0))
  })
})
