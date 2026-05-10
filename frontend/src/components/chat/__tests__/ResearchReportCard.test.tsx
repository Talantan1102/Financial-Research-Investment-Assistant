import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { ResearchReportCard } from '@/components/chat/ResearchReportCard'
import type { ChatMessage } from '@/types/chat'

const navigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => navigate }
})

function makeReportMsg(): ChatMessage {
  return {
    id: 'r1',
    session_id: 's1',
    role: 'assistant',
    content: '',
    message_type: 'research_report',
    tool_call_data: null,
    research_report_id: 'rep-42',
    research_report_summary: 'ICBC 2025Q1 ROE 11.2%, 净息差收窄但拨备覆盖率稳健,建议持有。',
    created_at: '2026-05-09T00:00:00Z',
  }
}

describe('<ResearchReportCard>', () => {
  it('renders summary text + report id', () => {
    render(<MemoryRouter><ResearchReportCard message={makeReportMsg()} /></MemoryRouter>)
    expect(screen.getByText(/ICBC 2025Q1/)).toBeInTheDocument()
    expect(screen.getByText(/rep-42/)).toBeInTheDocument()
  })

  it('renders 展开 / 跳转 Reports / 继续提问 three buttons', () => {
    render(<MemoryRouter><ResearchReportCard message={makeReportMsg()} /></MemoryRouter>)
    expect(screen.getByRole('button', { name: /展开/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /跳转 Reports/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /继续提问/ })).toBeInTheDocument()
  })

  it('navigates to /reports/:id on 跳转 click', async () => {
    const user = userEvent.setup()
    navigate.mockClear()
    render(<MemoryRouter><ResearchReportCard message={makeReportMsg()} /></MemoryRouter>)
    await user.click(screen.getByRole('button', { name: /跳转 Reports/ }))
    expect(navigate).toHaveBeenCalledWith('/reports/rep-42')
  })
})

describe('<ResearchReportCard> 继续提问 action', () => {
  it('invokes onContinueAsk(message.id) on 继续提问 click', async () => {
    const user = userEvent.setup()
    const onContinueAsk = vi.fn()
    render(
      <MemoryRouter>
        <ResearchReportCard message={makeReportMsg()} onContinueAsk={onContinueAsk} />
      </MemoryRouter>,
    )
    await user.click(screen.getByRole('button', { name: /继续提问/ }))
    expect(onContinueAsk).toHaveBeenCalledWith('r1')
  })
})
