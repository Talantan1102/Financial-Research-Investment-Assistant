import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'

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
          message_count: 0,
          last_msg_preview: null,
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
import { ConfigProvider } from 'antd'
import { ChatSessionList } from '../chat-session-list'

function renderList() {
  return render(
    <ConfigProvider>
      <MemoryRouter>
        <ChatSessionList />
      </MemoryRouter>
    </ConfigProvider>,
  )
}

describe('ChatSessionList rename', () => {
  beforeEach(() => {
    vi.mocked(chatSessionsActions.renameSession).mockReset()
  })

  it('shows ... button on hover and reveals dropdown with Rename', () => {
    renderList()
    const row = screen.getByText('old title').closest('[data-session-row]')!
    fireEvent.mouseEnter(row)
    const moreBtn = screen.getByRole('button', { name: /more|更多|\.\.\./i })
    fireEvent.click(moreBtn)
    expect(screen.getByText('重命名')).toBeInTheDocument()
  })

  it('Rename → inline input, Enter submits and calls store.renameSession', () => {
    vi.mocked(chatSessionsActions.renameSession).mockResolvedValue(undefined)
    renderList()
    const row = screen.getByText('old title').closest('[data-session-row]')!
    fireEvent.mouseEnter(row)
    fireEvent.click(screen.getByRole('button', { name: /more|更多|\.\.\./i }))
    fireEvent.click(screen.getByText('重命名'))
    const input = screen.getByRole('textbox') as HTMLInputElement
    fireEvent.change(input, { target: { value: 'new title' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(chatSessionsActions.renameSession).toHaveBeenCalledWith('a', 'new title')
  })

  it('Esc cancels and restores title display', () => {
    renderList()
    const row = screen.getByText('old title').closest('[data-session-row]')!
    fireEvent.mouseEnter(row)
    fireEvent.click(screen.getByRole('button', { name: /more|更多|\.\.\./i }))
    fireEvent.click(screen.getByText('重命名'))
    const input = screen.getByRole('textbox') as HTMLInputElement
    fireEvent.change(input, { target: { value: 'discard me' } })
    fireEvent.keyDown(input, { key: 'Escape' })
    expect(chatSessionsActions.renameSession).not.toHaveBeenCalled()
    expect(screen.getByText('old title')).toBeInTheDocument()
  })
})
