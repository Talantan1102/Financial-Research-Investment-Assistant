import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

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
import { chatSessionsActions } from '@/store/chat-sessions'
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
    const meta = screen.getByText(/3 turns/)
    expect(meta).toBeInTheDocument()
  })

  it('session item has data-testid anchor', () => {
    renderList()
    expect(screen.getByTestId('session-item-a')).toBeInTheDocument()
  })
})

describe('ChatSessionList rename UI', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('more button exists in DOM and clicking reveals rename menu', async () => {
    renderList()
    const user = userEvent.setup()

    // more button is always in DOM (CSS opacity: 0 on hover, but DOM present)
    const moreBtn = screen.getByTestId('session-more-a')
    expect(moreBtn).toBeInTheDocument()

    // click opens menu
    await user.click(moreBtn)
    expect(screen.getByTestId('session-menu-a')).toBeInTheDocument()
    expect(screen.getByTestId('session-rename-a')).toBeInTheDocument()
    expect(screen.getByText('重命名')).toBeInTheDocument()
  })

  it('clicking rename → inline input appears with initial value', async () => {
    renderList()
    const user = userEvent.setup()

    await user.click(screen.getByTestId('session-more-a'))
    await user.click(screen.getByTestId('session-rename-a'))

    const input = await screen.findByTestId('rename-input')
    expect(input).toBeInTheDocument()
    expect((input as HTMLInputElement).value).toBe('old title')
  })

  it('Enter submits and calls renameSession with new value', async () => {
    vi.mocked(chatSessionsActions.renameSession).mockResolvedValue(undefined)
    renderList()
    const user = userEvent.setup()

    await user.click(screen.getByTestId('session-more-a'))
    await user.click(screen.getByTestId('session-rename-a'))

    const input = await screen.findByTestId('rename-input')
    await user.clear(input)
    await user.type(input, 'new title{Enter}')

    await waitFor(() => {
      expect(chatSessionsActions.renameSession).toHaveBeenCalledWith('a', 'new title')
    })
  })

  it('Esc cancels and does not call renameSession', async () => {
    renderList()
    const user = userEvent.setup()

    await user.click(screen.getByTestId('session-more-a'))
    await user.click(screen.getByTestId('session-rename-a'))

    const input = await screen.findByTestId('rename-input')
    fireEvent.keyDown(input, { key: 'Escape' })

    await waitFor(() => {
      expect(screen.queryByTestId('rename-input')).toBeNull()
    })
    expect(chatSessionsActions.renameSession).not.toHaveBeenCalled()
  })

  it('blank title does not call renameSession', async () => {
    vi.mocked(chatSessionsActions.renameSession).mockResolvedValue(undefined)
    renderList()
    const user = userEvent.setup()

    await user.click(screen.getByTestId('session-more-a'))
    await user.click(screen.getByTestId('session-rename-a'))

    const input = await screen.findByTestId('rename-input')
    await user.clear(input)
    await user.type(input, '   {Enter}')

    await waitFor(() => {
      expect(screen.queryByTestId('rename-input')).toBeNull()
    })
    expect(chatSessionsActions.renameSession).not.toHaveBeenCalled()
  })
})
