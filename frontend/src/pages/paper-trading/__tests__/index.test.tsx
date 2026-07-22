import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import PaperTradingPage from '@/pages/paper-trading'

vi.mock('@/api/paperTrading', () => ({
  getAccount: vi.fn().mockResolvedValue({ id: 'a', generation: 1, initial_cash: '10000.00', available_cash: '8000.00', frozen_cash: '2000.00', status: 'active' }),
  listHoldings: vi.fn().mockResolvedValue([{ generation: 1, ts_code: '600000.SH', name: '浦发银行', quantity: 200, frozen_quantity: 100, sellable_quantity: 100, average_cost: '10.00' }]),
  listOrders: vi.fn().mockResolvedValue([]), listFills: vi.fn().mockResolvedValue([]), listCashLedger: vi.fn().mockResolvedValue([]),
  previewReset: vi.fn(), confirmReset: vi.fn(), confirmOrder: vi.fn(), confirmCancel: vi.fn(), getOrder: vi.fn(), previewOrder: vi.fn(), previewCancel: vi.fn(),
}))

describe('PaperTradingPage', () => {
  it('renders account balances and distinguishes total from sellable quantity', async () => {
    render(<PaperTradingPage />)
    expect(await screen.findByText('可用资金')).toBeInTheDocument()
    expect(await screen.findByText('200')).toBeInTheDocument()
    expect(await screen.findByText('可卖 100')).toBeInTheDocument()
  })

  it('offers reset only through a preview confirmation flow', async () => {
    render(<PaperTradingPage />)
    await waitFor(() => expect(screen.getByRole('button', { name: '重置账户' })).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: '重置模拟账户' })).not.toBeInTheDocument()
  })
})
