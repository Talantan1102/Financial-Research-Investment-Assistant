import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
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

// TextMessage needs router context (Plan 7B Task 6: useNavigate for
// `[查看](#mem-id)` anchor 拦截). 老测试用 MemoryRouter 包一层即可.
function withRouter(content: string, role: 'user' | 'assistant' = 'assistant') {
  return (
    <MemoryRouter>
      <TextMessage message={m(content, role)} />
    </MemoryRouter>
  )
}

describe('<TextMessage> KaTeX', () => {
  it('renders inline math $...$ via KaTeX', () => {
    render(withRouter('Euler: $e^{i\\pi}+1=0$'))
    expect(document.querySelector('.katex')).not.toBeNull()
  })

  it('renders display math $$...$$ as block', () => {
    render(withRouter('$$\\sum_{i=1}^n i = \\frac{n(n+1)}{2}$$'))
    expect(document.querySelector('.katex-display')).not.toBeNull()
  })
})

describe('<TextMessage> markdown', () => {
  it('renders **bold** as <strong>', () => {
    render(withRouter('this is **bold**'))
    expect(screen.getByText('bold').tagName).toBe('STRONG')
  })

  it('renders ```python fenced code with hljs class', () => {
    render(withRouter('```python\nprint("hi")\n```'))
    const pre = document.querySelector('pre code.hljs')
    expect(pre).not.toBeNull()
    expect(pre?.className).toContain('language-python')
  })

  it('renders inline code with <code>', () => {
    render(withRouter('use `useState` hook'))
    expect(screen.getByText('useState').tagName).toBe('CODE')
  })

  it('renders user role with different styling class', () => {
    const { container } = render(withRouter('hi', 'user'))
    expect(container.querySelector('[data-role="user"]')).not.toBeNull()
  })

  it('escapes raw HTML to prevent XSS', () => {
    render(withRouter('<script>alert(1)</script>hello'))
    expect(document.querySelector('script')).toBeNull()
    expect(screen.getByText(/hello/)).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// Plan 7B Task 6 — `[查看](#mem-{edge_id})` anchor 拦截
// ---------------------------------------------------------------------------

describe('<TextMessage> memory anchor', () => {
  it('clicking [查看](#mem-xxx) navigates to /memory?highlight_edge=xxx', async () => {
    const LocationDisplay = () => {
      const loc = useLocation()
      return <div data-testid="loc">{loc.pathname + loc.search}</div>
    }
    const { container } = render(
      <MemoryRouter initialEntries={['/chat']}>
        <TextMessage
          message={m('基于您的偏好([查看](#mem-abc-123)), 建议...')}
        />
        <LocationDisplay />
      </MemoryRouter>,
    )
    const link = container.querySelector(
      'a[href="#mem-abc-123"]',
    ) as HTMLAnchorElement | null
    expect(link).not.toBeNull()
    fireEvent.click(link!)
    expect(screen.getByTestId('loc').textContent).toContain(
      '/memory?highlight_edge=abc-123',
    )
  })

  it('regular http link is not intercepted (location stays at /chat)', () => {
    const LocationDisplay = () => {
      const loc = useLocation()
      return <div data-testid="loc">{loc.pathname + loc.search}</div>
    }
    const { container } = render(
      <MemoryRouter initialEntries={['/chat']}>
        <TextMessage message={m('参考 [百度](https://baidu.com)')} />
        <LocationDisplay />
      </MemoryRouter>,
    )
    const link = container.querySelector(
      'a[href="https://baidu.com"]',
    ) as HTMLAnchorElement | null
    expect(link).not.toBeNull()
    // 不抛 navigation, 仍是普通 link (jsdom 不真 navigate, 但路径不应变成 /memory).
    fireEvent.click(link!)
    expect(screen.getByTestId('loc').textContent).toBe('/chat')
  })
})
