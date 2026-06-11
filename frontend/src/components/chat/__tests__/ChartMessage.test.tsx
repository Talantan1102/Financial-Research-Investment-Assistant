import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ChartMessage } from '../ChartMessage'
import type { ChatMessage } from '@/types/chat'

// PlotlySpecRenderer pulls in plotly (jsdom can't run it) → mock it to a stub.
vi.mock('../PlotlySpecRenderer', () => ({
  PlotlySpecRenderer: ({ spec }: { spec: { figure: { data: unknown[] } } }) => (
    <div data-testid="plot" data-traces={String((spec?.figure?.data ?? []).length)} />
  ),
}))

function chartMsg(): ChatMessage {
  return {
    id: 'local-chart-x',
    session_id: 's',
    role: 'assistant',
    content: '',
    message_type: 'chart',
    tool_call_data: null,
    research_report_id: null,
    research_report_summary: null,
    created_at: '2026-06-11T00:00:00Z',
    chart_spec: { type: 'plotly', figure: { data: [{ type: 'bar' }], layout: {} } },
  }
}

describe('ChartMessage', () => {
  it('renders the plotly figure', () => {
    render(<ChartMessage message={chartMsg()} />)
    expect(screen.getByTestId('plot').getAttribute('data-traces')).toBe('1')
  })

  it('renders nothing when chart_spec missing', () => {
    const m = { ...chartMsg(), chart_spec: undefined }
    const { container } = render(<ChartMessage message={m} />)
    expect(container.querySelector('[data-testid="plot"]')).toBeNull()
  })
})
