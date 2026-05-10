import { describe, expect, it, beforeEach } from 'vitest'
import { fireEvent, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { useLocation } from 'react-router-dom'
import { renderWithProviders } from '@/test-utils/render'
import { server } from '@/test-utils/msw-server'
import { ChatSessionList } from '@/components/sidebar/chat-session-list'
import { chatSessionsActions } from '@/store/chat-sessions'

const API_BASE = (import.meta.env.VITE_API_BASE as string) ?? ''

function Probe({ onLoc }: { onLoc: (p: string) => void }) {
  onLoc(useLocation().pathname)
  return null
}

describe('<ChatSessionList>', () => {
  beforeEach(() => chatSessionsActions.reset())

  it('lists sessions sorted by last_active_at desc and navigates on click', async () => {
    server.use(
      http.get(`${API_BASE}/api/v0/chats`, () =>
        HttpResponse.json([
          { id: 'a', user_id: null, title: 'old', created_at: '2026-05-09T00:00:00Z', last_active_at: '2026-05-09T00:00:00Z', message_count: 0, last_msg_preview: null },
          { id: 'b', user_id: null, title: 'new', created_at: '2026-05-09T00:00:00Z', last_active_at: '2026-05-09T01:00:00Z', message_count: 0, last_msg_preview: null },
        ]),
      ),
    )
    let path = ''
    const { findByText } = renderWithProviders(
      <>
        <ChatSessionList />
        <Probe onLoc={(p) => { path = p }} />
      </>,
    )
    const newItem = await findByText('new')
    expect(newItem).toBeInTheDocument()
    fireEvent.click(newItem)
    await waitFor(() => expect(path).toBe('/chat/b'))
  })
})
