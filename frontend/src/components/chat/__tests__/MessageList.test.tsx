import { render } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { MessageList } from '@/components/chat/MessageList'
import type { ChatMessage } from '@/types/chat'

vi.mock('@/components/chat/TextMessage', () => ({
  TextMessage: ({ message }: { message: ChatMessage }) => <div data-testid={`text-${message.id}`}>{message.content}</div>,
}))
vi.mock('@/components/chat/ToolCallCard', () => ({
  ToolCallCard: ({ message }: { message: ChatMessage }) => <div data-testid={`tool-${message.id}`} />,
}))
vi.mock('@/components/chat/ResearchReportCard', () => ({
  ResearchReportCard: ({ message }: { message: ChatMessage }) => <div data-testid={`report-${message.id}`} />,
}))
vi.mock('@/components/chat/SystemMessage', () => ({
  SystemMessage: ({ message }: { message: ChatMessage }) => <div data-testid={`sys-${message.id}`} />,
}))

function makeMsg(over: Partial<ChatMessage>): ChatMessage {
  return {
    id: 'm1',
    session_id: 's1',
    role: 'assistant',
    content: 'hi',
    message_type: 'text',
    tool_call_data: null,
    research_report_id: null,
    research_report_summary: null,
    created_at: '2026-05-09T00:00:00Z',
    ...over,
  }
}

describe('<MessageList> routing + virtualization', () => {
  it('routes text → TextMessage', () => {
    const { getByTestId } = render(
      <MessageList messages={[makeMsg({ id: 'a', message_type: 'text', content: 'hello' })]} />,
    )
    expect(getByTestId('text-a')).toHaveTextContent('hello')
  })

  it('routes tool_call → ToolCallCard', () => {
    const { getByTestId } = render(
      <MessageList messages={[makeMsg({ id: 'b', message_type: 'tool_call' })]} />,
    )
    expect(getByTestId('tool-b')).toBeInTheDocument()
  })

  it('routes research_report → ResearchReportCard', () => {
    const { getByTestId } = render(
      <MessageList messages={[makeMsg({ id: 'c', message_type: 'research_report' })]} />,
    )
    expect(getByTestId('report-c')).toBeInTheDocument()
  })

  it('routes system → SystemMessage', () => {
    const { getByTestId } = render(
      <MessageList messages={[makeMsg({ id: 'd', message_type: 'system' })]} />,
    )
    expect(getByTestId('sys-d')).toBeInTheDocument()
  })

  it('virtualizes — at 1000 messages only ~20 are mounted at once (F1)', () => {
    const msgs = Array.from({ length: 1000 }, (_, i) =>
      makeMsg({ id: `x${i}`, content: `m${i}` }),
    )
    const { container } = render(<MessageList messages={msgs} />)
    const rendered = container.querySelectorAll('[data-testid^="text-"]')
    expect(rendered.length).toBeLessThan(60)
  })
})
