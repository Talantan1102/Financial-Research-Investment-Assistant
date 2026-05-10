import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import ReportsListPage from '@/pages/reports'

vi.mock('@/api/reportsApi', () => ({
  listReports: vi.fn(async () => [
    {
      id: 'r1',
      title: 'ICBC 2025Q1 尽调',
      source_chat_session_id: 'c1',
      created_at: '2026-05-09T00:00:00Z',
      cost_usd: 0.087,
    },
    {
      id: 'r2',
      title: '招行同业对比',
      source_chat_session_id: null,
      created_at: '2026-05-08T00:00:00Z',
      cost_usd: 0.064,
    },
  ]),
  getReport: vi.fn(async (id: string) => ({
    id,
    title: 't',
    source_chat_session_id: null,
    created_at: '2026-05-09T00:00:00Z',
    cost_usd: 0,
    content_md: '# hello',
    metadata: {},
  })),
}))

describe('<ReportsListPage>', () => {
  it('renders list of reports from API', async () => {
    render(
      <MemoryRouter>
        <ReportsListPage />
      </MemoryRouter>,
    )
    await waitFor(() =>
      expect(screen.getByText(/ICBC 2025Q1 尽调/)).toBeInTheDocument(),
    )
    expect(screen.getByText(/招行同业对比/)).toBeInTheDocument()
  })

  it('shows source chat link only when source_chat_session_id present', async () => {
    render(
      <MemoryRouter>
        <ReportsListPage />
      </MemoryRouter>,
    )
    await waitFor(() =>
      expect(screen.getByText(/ICBC 2025Q1 尽调/)).toBeInTheDocument(),
    )
    expect(screen.getByRole('link', { name: /回到 chat/i })).toHaveAttribute(
      'href',
      '/chat/c1',
    )
  })

  it('opens detail modal on row click', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <ReportsListPage />
      </MemoryRouter>,
    )
    await waitFor(() =>
      expect(screen.getByText(/ICBC 2025Q1 尽调/)).toBeInTheDocument(),
    )
    await user.click(screen.getByText(/ICBC 2025Q1 尽调/))
    await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument())
  })
})
