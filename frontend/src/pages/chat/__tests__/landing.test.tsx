import { describe, expect, it, beforeEach } from 'vitest'
import { http, HttpResponse } from 'msw'
import { useLocation } from 'react-router-dom'
import { waitFor } from '@testing-library/react'
import { renderWithProviders } from '@/test-utils/render'
import { server } from '@/test-utils/msw-server'
import ChatLandingPage from '@/pages/chat/landing'
import { chatSessionsActions } from '@/store/chat-sessions'

const API_BASE = (import.meta.env.VITE_API_BASE as string) ?? ''

function Probe({ onLoc }: { onLoc: (p: string) => void }) {
  onLoc(useLocation().pathname)
  return null
}

describe('<ChatLandingPage>', () => {
  beforeEach(() => chatSessionsActions.reset())

  it('auto-creates a session and redirects to /chat/:id', async () => {
    server.use(
      http.post(`${API_BASE}/api/v0/chats`, () =>
        HttpResponse.json({
          id: 'auto-1', user_id: null, title: 'New chat',
          created_at: '2026-05-09T00:00:00Z', last_active_at: '2026-05-09T00:00:00Z',
          message_count: 0, last_msg_preview: null,
        }),
      ),
    )
    let path = ''
    renderWithProviders(
      <>
        <ChatLandingPage />
        <Probe onLoc={(p) => { path = p }} />
      </>,
      { initialRoute: '/chat' },
    )
    await waitFor(() => expect(path).toBe('/chat/auto-1'))
  })
})
