import { describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import PortfolioOverviewPage from '../index'

vi.mock('@/api/portfolio', () => ({
  getOverview: () =>
    Promise.resolve({
      data: {
        total_value: 319000,
        today_pct: -2.1,
        ytd_pct: 12.4,
        attribution: {
          total_pct: -2.1,
          by_class: { stock: -2.0, fund_otc: -0.1 },
          stock_breakdown: { market: -0.9, sector_excess: -0.8, idiosyncratic: -0.3 },
          contributions: [],
        },
        structure: {
          by_class: { stock: 0.58, fund_otc: 0.22 },
          by_sector: { 白酒: 0.46 },
          as_of: '2026-09-30',
        },
        narrative: '今天主要是白酒砸的。',
      },
    }),
  getTrend: () =>
    Promise.resolve({
      data: {
        dates: ['1', '2'],
        portfolio: [0.01],
        benchmark: [0.005],
        cumulative: 0.032,
        range: '1m',
      },
    }),
}))

describe('PortfolioOverviewPage', () => {
  it('渲染头条总身家与今天涨跌', async () => {
    render(
      <MemoryRouter>
        <PortfolioOverviewPage />
      </MemoryRouter>,
    )
    await waitFor(() =>
      expect(screen.getByText(/总身家/)).toBeInTheDocument(),
    )
    expect(screen.getByText(/319,?000|31\.9/)).toBeInTheDocument()
  })

  it('渲染 AI 叙事文案', async () => {
    render(
      <MemoryRouter>
        <PortfolioOverviewPage />
      </MemoryRouter>,
    )
    await waitFor(() =>
      expect(screen.getByText(/白酒砸的/)).toBeInTheDocument(),
    )
  })
})
