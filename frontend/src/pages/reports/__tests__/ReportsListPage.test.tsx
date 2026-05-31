/**
 * Tests for ReportsListPage.
 *
 * Mock target updated from @/api/reportsApi (zombie) to @/api/reports (correct SSOT).
 * Mock data uses actual backend ReportListItem schema: target_name, cost, status,
 * investment_recommendation — NOT the old ghost fields title/cost_usd/content_md.
 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import ReportsListPage from '@/pages/reports'

vi.mock('@/api/reports', () => ({
  listReports: vi.fn(async () => ({
    data: {
      items: [
        {
          id: 'r1',
          target_name: '工商银行 2025Q1 尽调',
          target_ts_code: '601398.SH',
          status: 'completed',
          cost: 0.087,
          created_at: '2026-05-09T00:00:00Z',
          investment_recommendation: 'recommend_buy',
        },
        {
          id: 'r2',
          target_name: '招行同业对比',
          target_ts_code: null,
          status: 'completed',
          cost: 0.064,
          created_at: '2026-05-08T00:00:00Z',
          investment_recommendation: null,
        },
      ],
      total: 2,
      page: 1,
      page_size: 100,
    },
  })),
  getReport: vi.fn(async (id: string) => ({
    data: {
      id,
      target_name: '工商银行 2025Q1 尽调',
      target_ts_code: '601398.SH',
      status: 'completed',
      cost: 0.087,
      created_at: '2026-05-09T00:00:00Z',
      updated_at: '2026-05-09T01:00:00Z',
      request_id: 'req-1',
      report_json: { report_markdown: '# 研报正文' },
    },
  })),
}))

describe('<ReportsListPage>', () => {
  it('renders list of reports from API using target_name column', async () => {
    render(
      <MemoryRouter>
        <ReportsListPage />
      </MemoryRouter>,
    )
    await waitFor(() =>
      expect(screen.getByText(/工商银行 2025Q1 尽调/)).toBeInTheDocument(),
    )
    expect(screen.getByText(/招行同业对比/)).toBeInTheDocument()
  })

  it('shows total count in card header', async () => {
    render(
      <MemoryRouter>
        <ReportsListPage />
      </MemoryRouter>,
    )
    await waitFor(() =>
      expect(screen.getByText(/工商银行 2025Q1 尽调/)).toBeInTheDocument(),
    )
    expect(screen.getByText(/2 份/)).toBeInTheDocument()
  })

  it('opens detail modal on row click', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <ReportsListPage />
      </MemoryRouter>,
    )
    await waitFor(() =>
      expect(screen.getByText(/工商银行 2025Q1 尽调/)).toBeInTheDocument(),
    )
    await user.click(screen.getByText(/工商银行 2025Q1 尽调/))
    await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument())
  })
})
