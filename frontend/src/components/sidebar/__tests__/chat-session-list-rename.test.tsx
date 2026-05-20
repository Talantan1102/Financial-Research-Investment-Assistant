/**
 * chat-session-list-rename.test.tsx
 *
 * NOTE(Task 5 refactor): The rename dropdown UI has been removed from
 * ChatSessionList as part of the iOS-polish rewrite (antd List → native div
 * groups).  Renaming is now a separate concern (e.g. long-press / context
 * menu planned for v1.x).  Tests below verify the new session-item structure
 * instead.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'

vi.mock('@/store/chat-sessions', async () => {
  const { proxy } = await import('valtio')
  return {
    chatSessionsState: proxy({
      sessions: [
        {
          id: 'a',
          user_id: null,
          title: 'old title',
          created_at: '2026-05-17T00:00:00Z',
          last_active_at: '2026-05-17T00:00:00Z',
          message_count: 3,
          last_msg_preview: 'hello world',
        },
      ],
      status: 'loaded',
      error: null,
    }),
    chatSessionsActions: {
      renameSession: vi.fn(),
      loadSessions: vi.fn().mockResolvedValue(undefined),
    },
  }
})

// Import store after mock
import { MemoryRouter } from 'react-router-dom'
import { ChatSessionList } from '../chat-session-list'

function renderList() {
  return render(
    <MemoryRouter>
      <ChatSessionList />
    </MemoryRouter>,
  )
}

describe('ChatSessionList (iOS-polish structure)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders session title', () => {
    renderList()
    expect(screen.getByText('old title')).toBeInTheDocument()
  })

  it('renders last_msg_preview when present', () => {
    renderList()
    expect(screen.getByText('hello world')).toBeInTheDocument()
  })

  it('renders session meta with message_count', () => {
    renderList()
    // meta line includes "· N turns"
    const meta = screen.getByText(/3 turns/)
    expect(meta).toBeInTheDocument()
  })

  it('session item has data-testid anchor', () => {
    renderList()
    expect(screen.getByTestId('session-item-a')).toBeInTheDocument()
  })
})
