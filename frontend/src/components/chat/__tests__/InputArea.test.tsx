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

  it('hides send button and shows 中断 when streaming_phase != idle', () => {
    currentChatState.streaming_phase = 'thinking'
    render(<InputArea sessionId="s1" />)
    expect(screen.queryByRole('button', { name: /发送|send/i })).toBeNull()
    expect(screen.getByRole('button', { name: /中断|abort/i })).toBeInTheDocument()
  })
})

describe('<InputArea> Cmd+K abort', () => {
  it('shows 中断 button while streaming, hides 发送', () => {
    currentChatState.streaming_phase = 'writing'
    render(<InputArea sessionId="s1" />)
    expect(screen.getByRole('button', { name: /中断|abort/i })).toBeInTheDocument()
  })

  it('Cmd+K calls onAbort while streaming', async () => {
    currentChatState.streaming_phase = 'writing'
    const onAbort = vi.fn()
    const user = userEvent.setup()
    render(<InputArea sessionId="s1" onAbort={onAbort} />)
    await user.keyboard('{Meta>}k{/Meta}')
    expect(onAbort).toHaveBeenCalled()
  })

  it('Ctrl+K also triggers abort (cross-platform)', async () => {
    currentChatState.streaming_phase = 'writing'
    const onAbort = vi.fn()
    const user = userEvent.setup()
    render(<InputArea sessionId="s1" onAbort={onAbort} />)
    await user.keyboard('{Control>}k{/Control}')
    expect(onAbort).toHaveBeenCalled()
  })
})

describe('<InputArea> Escalate button', () => {
  beforeEach(() => {
    currentChatActions.reset()
  })

  it('renders ⚡ Escalate button when not streaming and chat has at least 1 message', () => {
    currentChatActions.setSession('s1', [
      {
        id: 'a',
        session_id: 's1',
        role: 'user',
        content: 'q?',
        message_type: 'text',
        tool_call_data: null,
        research_report_id: null,
        research_report_summary: null,
        created_at: '2026-05-09T00:00:00Z',
      },
    ])
    render(<InputArea sessionId="s1" />)
    expect(screen.getByRole('button', { name: /Escalate|升级到深度研究|⚡/i })).toBeInTheDocument()
  })

  it('hides Escalate button on empty chat', () => {
    currentChatActions.setSession('s1', [])
    render(<InputArea sessionId="s1" />)
    expect(screen.queryByRole('button', { name: /Escalate|升级到深度研究|⚡/i })).toBeNull()
  })

  it('clicking Escalate calls onEscalate', async () => {
    currentChatActions.setSession('s1', [
      {
        id: 'a',
        session_id: 's1',
        role: 'user',
        content: 'q?',
        message_type: 'text',
        tool_call_data: null,
        research_report_id: null,
        research_report_summary: null,
        created_at: '2026-05-09T00:00:00Z',
      },
    ])
    const onEscalate = vi.fn()
    const user = userEvent.setup()
    render(<InputArea sessionId="s1" onEscalate={onEscalate} />)
    await user.click(screen.getByRole('button', { name: /Escalate|升级到深度研究|⚡/i }))
    expect(onEscalate).toHaveBeenCalled()
  })
})
