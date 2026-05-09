import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { ToolCallCard } from '@/components/chat/ToolCallCard'
import type { ChatMessage, ToolCallData } from '@/types/chat'

function makeToolMsg(data: Partial<ToolCallData>): ChatMessage {
  return {
    id: 't1',
    session_id: 's1',
    role: 'assistant',
    content: '',
    message_type: 'tool_call',
    tool_call_data: {
      tool_name: 'get_stock_quote',
      tool_args: { ts_code: '601398.SH' },
      status: 'success',
      result_summary: 'price 5.43',
      started_at: '2026-05-09T00:00:00Z',
      ended_at: '2026-05-09T00:00:01Z',
      ...data,
    } as unknown as Record<string, unknown>,
    research_report_id: null,
    research_report_summary: null,
    created_at: '2026-05-09T00:00:00Z',
  }
}

describe('<ToolCallCard> collapsed state', () => {
  it('renders tool name + duration in collapsed view by default', () => {
    render(<ToolCallCard message={makeToolMsg({})} />)
    expect(screen.getByText(/get_stock_quote/)).toBeInTheDocument()
    expect(screen.getByText(/1s/)).toBeInTheDocument()
    expect(screen.queryByText(/601398\.SH/)).toBeNull()
  })

  it('expands on click to show args + result_summary', async () => {
    const user = userEvent.setup()
    render(<ToolCallCard message={makeToolMsg({})} />)
    await user.click(screen.getByRole('button', { name: /展开|expand/i }))
    expect(screen.getByText(/601398\.SH/)).toBeInTheDocument()
    expect(screen.getByText(/price 5\.43/)).toBeInTheDocument()
  })

  it('shows running spinner when status=running', () => {
    render(<ToolCallCard message={makeToolMsg({ status: 'running', ended_at: undefined })} />)
    expect(screen.getByTestId('tool-running-spinner')).toBeInTheDocument()
  })
})
