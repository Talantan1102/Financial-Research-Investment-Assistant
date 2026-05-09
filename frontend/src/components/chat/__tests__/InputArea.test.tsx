import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { InputArea } from '@/components/chat/InputArea'
import { currentChatActions, currentChatState } from '@/store/current-chat'

describe('<InputArea>', () => {
  beforeEach(() => {
    currentChatActions.reset()
  })

  it('renders textarea + send button', () => {
    render(<InputArea sessionId="s1" />)
    expect(screen.getByRole('textbox')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /发送|send/i })).toBeInTheDocument()
  })

  it('Enter sends message; clears textarea', async () => {
    const onSend = vi.fn()
    const user = userEvent.setup()
    render(<InputArea sessionId="s1" onSend={onSend} />)
    const ta = screen.getByRole('textbox')
    await user.type(ta, 'hello{Enter}')
    expect(onSend).toHaveBeenCalledWith('hello')
    expect(ta).toHaveValue('')
  })

  it('Shift+Enter inserts newline; does NOT send', async () => {
    const onSend = vi.fn()
    const user = userEvent.setup()
    render(<InputArea sessionId="s1" onSend={onSend} />)
    const ta = screen.getByRole('textbox')
    await user.type(ta, 'line1{Shift>}{Enter}{/Shift}line2')
    expect(onSend).not.toHaveBeenCalled()
    expect(ta).toHaveValue('line1\nline2')
  })

  it('auto-resizes textarea height as content grows', async () => {
    const user = userEvent.setup()
    render(<InputArea sessionId="s1" />)
    const ta = screen.getByRole('textbox') as HTMLTextAreaElement
    await user.type(ta, 'one\ntwo\nthree\nfour\nfive\nsix')
    // jsdom scrollHeight is 0; verify autoResize ran by checking style.height is set
    expect(ta.style.height).toBeTruthy()
  })

  it('disables send when streaming_phase != idle', () => {
    currentChatState.streaming_phase = 'thinking'
    render(<InputArea sessionId="s1" />)
    const btn = screen.getByRole('button', { name: /发送|send/i }) as HTMLButtonElement
    expect(btn.disabled).toBe(true)
  })
})
