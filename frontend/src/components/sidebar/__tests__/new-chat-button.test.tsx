import { describe, expect, it, beforeEach } from 'vitest'
import { fireEvent, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { useLocation } from 'react-router-dom'
import { renderWithProviders } from '@/test-utils/render'
import { server } from '@/test-utils/msw-server'
import { NewChatButton } from '@/components/sidebar/new-chat-button'
import { chatSessionsActions } from '@/store/chat-sessions'

const API_BASE = (import.meta.env.VITE_API_BASE as string) ?? ''

function LocationProbe({ onLoc }: { onLoc: (path: string) => void }) {
  const loc = useLocation()
  onLoc(loc.pathname)
  return null
}

describe('<NewChatButton>', () => {
  beforeEach(() => chatSessionsActions.reset())

  it('clicking creates a chat and navigates to /chat/:id', async () => {
    server.use(
      http.post(`${API_BASE}/api/v0/chats`, () =>
        HttpResponse.json({
          id: 'new-id',
          user_id: null,
          title: 'New chat',
          created_at: '2026-05-09T00:00:00Z',
          last_active_at: '2026-05-09T00:00:00Z',
          message_count: 0,
          last_msg_preview: null,
        }),
      ),
    )
    let pathname = ''
    const { getByTestId } = renderWithProviders(
      <>
        <NewChatButton />
        <LocationProbe onLoc={(p) => { pathname = p }} />
      </>,
    )
    fireEvent.click(getByTestId('sidebar-new-chat-button'))
    await waitFor(() => {
      expect(pathname).toBe('/chat/new-id')
    })
  })
})
