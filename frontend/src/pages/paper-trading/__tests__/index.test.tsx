import { renderWithProviders } from '@/test-utils/render'
import { screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({
  getPaperAccount: vi.fn(),
  listPaperHoldings: vi.fn(),
  listPaperOrders: vi.fn(),
}))

vi.mock('@/api/paperTrading', () => api)

import PaperTradingPage from '../index'

describe('PaperTradingPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.getPaperAccount.mockResolvedValue({
      id: 'account-1',
      generation: 3,
      initial_cash: '1000000.00',
      available_cash: '812345.67',
      frozen_cash: '1200.00',
      status: 'active',
    })
    api.listPaperHoldings.mockResolvedValue([
      {
        generation: 3,
        ts_code: '600519.SH',
        name: '贵州茅台',
        quantity: 200,
        frozen_quantity: 100,
        sellable_quantity: 100,
        average_cost: '1528.1250',
      },
    ])
    api.listPaperOrders.mockResolvedValue([
      {
        id: 'order-1',
        account_generation: 3,
        ts_code: '600519.SH',
        name: '贵州茅台',
        side: 'buy',
        order_type: 'limit',
        quantity: 100,
        limit_price: '1500.0000',
        filled_quantity: 0,
        avg_fill_price: null,
        reserved_cash: '150005.00',
        reserved_quantity: 0,
        status: 'open',
        created_at: '2026-07-24T01:00:00Z',
      },
    ])
  })

  it('loads account, holdings and orders from paper-trading APIs', async () => {
    renderWithProviders(<PaperTradingPage />)

    expect(screen.getByText('正在读取模拟账户…')).toBeInTheDocument()
    expect(await screen.findByText('¥812,345.67')).toBeInTheDocument()
    expect(screen.getByText('第 3 轮')).toBeInTheDocument()
    expect(screen.getAllByText('贵州茅台')).toHaveLength(2)
    expect(screen.getByText('200 股')).toBeInTheDocument()
    expect(screen.getByText('¥1,528.1250')).toBeInTheDocument()
    expect(screen.getByText('已报')).toBeInTheDocument()

    expect(api.getPaperAccount).toHaveBeenCalledOnce()
    expect(api.listPaperHoldings).toHaveBeenCalledOnce()
    expect(api.listPaperOrders).toHaveBeenCalledWith({ limit: 50 })
  })

  it('shows a useful error without inventing account values', async () => {
    api.getPaperAccount.mockRejectedValue(new Error('账户服务暂时不可用'))

    renderWithProviders(<PaperTradingPage />)

    expect(await screen.findByRole('alert')).toHaveTextContent(
      '账户服务暂时不可用',
    )
    expect(screen.queryByText('¥0.00')).not.toBeInTheDocument()
    await waitFor(() => expect(api.listPaperOrders).not.toHaveBeenCalled())
  })
})
