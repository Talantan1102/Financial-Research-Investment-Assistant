import { describe, expect, it, beforeEach } from 'vitest'
import { http, HttpResponse } from 'msw'
import { Route, Routes } from 'react-router-dom'
import { renderWithProviders } from '@/test-utils/render'
import { server } from '@/test-utils/msw-server'
import ChatSessionPage from '@/pages/chat/session'
import { currentChatActions } from '@/store/current-chat'

const API_BASE = (import.meta.env.VITE_API_BASE as string) ?? ''

describe('<ChatSessionPage>', () => {
  beforeEach(() => currentChatActions.reset())

  it('loads chat detail by route param and exposes ChatPane slot', async () => {
    server.use(
      http.get(`${API_BASE}/api/v0/chats/abc`, () =>
        HttpResponse.json({
          session: {
            id: 'abc', user_id: null, title: 'demo',
            created_at: '2026-05-09T00:00:00Z',
            last_active_at: '2026-05-09T00:00:00Z',
            message_count: 0, last_msg_preview: null,
          },
          messages: [],
        }),
      ),
    )
    const { findByTestId } = renderWithProviders(
      <Routes>
        <Route path="/chat/:session_id" element={<ChatSessionPage />} />
      </Routes>,
      { initialRoute: '/chat/abc' },
    )
    expect(await findByTestId('chat-pane-slot')).toBeInTheDocument()
  })
})
