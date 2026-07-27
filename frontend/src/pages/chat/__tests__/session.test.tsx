import { beforeEach, describe, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { Route, Routes } from 'react-router-dom'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test-utils/render'
import { server } from '@/test-utils/msw-server'
import ChatSessionPage from '@/pages/chat/session'
import { currentChatActions, currentChatState } from '@/store/current-chat'
import { chatSessionsActions } from '@/store/chat-sessions'

let runOptions: Record<string, unknown> | null = null
vi.mock('@/hooks/useRunSSE', () => ({
  useRunSSE: (options: Record<string, unknown>) => {
    runOptions = options
    return { sendPrompt: vi.fn(), cancelRun: vi.fn(), resumeRun: vi.fn(),
      resubmitPrompt: vi.fn(), abort: vi.fn(), status: 'idle', activeRunId: null, pause: null }
  },
}))

const API_BASE = (import.meta.env.VITE_API_BASE as string) ?? ''
const now = '2026-05-09T00:00:00Z'

describe('<ChatSessionPage>', () => {
  beforeEach(() => {
    currentChatActions.reset()
    chatSessionsActions.reset()
  })

  it('loads durable history from tenant-scoped v1 detail and never calls v0', async () => {
    server.use(
      http.get(`${API_BASE}/api/v1/tenants`, () => HttpResponse.json([
        { id: 'tenant-1', name: 'Personal', is_personal: true, role: 'owner' },
      ])),
      http.get(`${API_BASE}/api/v1/tenants/tenant-1/sessions/abc`, () => HttpResponse.json({
        id: 'abc', tenant_id: 'tenant-1', created_by_user_id: 'u', title: 'demo',
        created_at: now, updated_at: now, archived_at: null, has_more: false,
        active_run_id: 'run-active', active_run_status: 'waiting_input',
        active_pause_id: 'pause-input',
        active_pause_type: 'input', active_pause_request: { question: '成本价？' },
        messages: [{ id: 'm1', role: 'assistant', content: 'durable answer', status: 'done', created_at: now }],
      })),
    )
    const { findByText } = renderWithProviders(
      <Routes><Route path="/chat/:session_id" element={<ChatSessionPage />} /></Routes>,
      { initialRoute: '/chat/abc' },
    )
    expect(await findByText('durable answer')).toBeInTheDocument()
    await waitFor(() => expect(currentChatState.session_id).toBe('abc'))
    await waitFor(() => expect(runOptions).toEqual(expect.objectContaining({
      initialRunId: 'run-active', initialRunStatus: 'waiting_input',
      initialPause: { id: 'pause-input', type: 'input_request', request: { question: '成本价？' } },
    })))
  })

  it('shows a safe detail error and retries history, active Run and pause recovery', async () => {
    let detailAttempts = 0
    server.use(
      http.get(`${API_BASE}/api/v1/tenants`, () => HttpResponse.json([
        { id: 'tenant-1', name: 'Personal', is_personal: true, role: 'owner' },
      ])),
      http.get(`${API_BASE}/api/v1/tenants/tenant-1/sessions/retry`, () => {
        detailAttempts += 1
        if (detailAttempts === 1) return HttpResponse.json({ secret: 'internal' }, { status: 503 })
        return HttpResponse.json({
          id: 'retry', tenant_id: 'tenant-1', created_by_user_id: 'u', title: 'demo',
          created_at: now, updated_at: now, archived_at: null, has_more: false,
          active_run_id: 'run-recovered', active_run_status: 'waiting_approval',
          active_pause_id: 'pause-approval',
          active_pause_type: 'approval', active_pause_request: { tools: [{ name: 'quote', arguments: { symbol: '600000' } }] },
          messages: [{ id: 'm2', role: 'assistant', content: 'recovered history', status: 'done', created_at: now }],
        })
      }),
    )
    renderWithProviders(
      <Routes><Route path="/chat/:session_id" element={<ChatSessionPage />} /></Routes>,
      { initialRoute: '/chat/retry' },
    )

    expect(await screen.findByRole('alert')).toHaveTextContent('会话加载失败，请重试')
    expect(screen.queryByText(/503|internal|GET \/api/)).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '重试' }))

    expect(await screen.findByText('recovered history')).toBeInTheDocument()
    await waitFor(() => expect(runOptions).toEqual(expect.objectContaining({
      initialRunId: 'run-recovered', initialRunStatus: 'waiting_approval',
      initialPause: expect.objectContaining({ type: 'approval_request' }),
    })))
    expect(detailAttempts).toBe(2)
  })
})
