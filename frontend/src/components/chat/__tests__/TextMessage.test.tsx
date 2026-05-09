import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { TextMessage } from '@/components/chat/TextMessage'
import type { ChatMessage } from '@/types/chat'

function m(content: string, role: 'user' | 'assistant' = 'assistant'): ChatMessage {
  return {
    id: '1',
    session_id: 's',
    role,
    content,
    message_type: 'text',
    tool_call_data: null,
    research_report_id: null,
    research_report_summary: null,
    created_at: '2026-05-09T00:00:00Z',
  }
}

describe('<TextMessage> markdown', () => {
  it('renders **bold** as <strong>', () => {
    render(<TextMessage message={m('this is **bold**')} />)
    expect(screen.getByText('bold').tagName).toBe('STRONG')
  })

  it('renders ```python fenced code with hljs class', () => {
    render(<TextMessage message={m('```python\nprint("hi")\n```')} />)
    const pre = document.querySelector('pre code.hljs')
    expect(pre).not.toBeNull()
    expect(pre?.className).toContain('language-python')
  })

  it('renders inline code with <code>', () => {
    render(<TextMessage message={m('use `useState` hook')} />)
    expect(screen.getByText('useState').tagName).toBe('CODE')
  })

  it('renders user role with different styling class', () => {
    const { container } = render(<TextMessage message={m('hi', 'user')} />)
    expect(container.querySelector('[data-role="user"]')).not.toBeNull()
  })

  it('escapes raw HTML to prevent XSS', () => {
    render(<TextMessage message={m('<script>alert(1)</script>hello')} />)
    expect(document.querySelector('script')).toBeNull()
    expect(screen.getByText(/hello/)).toBeInTheDocument()
  })
})
