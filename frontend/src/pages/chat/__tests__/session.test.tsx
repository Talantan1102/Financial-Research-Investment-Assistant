import { beforeEach, describe, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { Route, Routes } from 'react-router-dom'
import { waitFor } from '@testing-library/react'
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
      initialPause: { type: 'input_request', request: { question: '成本价？' } },
    })))
  })
})
