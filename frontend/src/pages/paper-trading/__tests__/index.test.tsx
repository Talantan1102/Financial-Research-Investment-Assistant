import { renderWithProviders } from '@/test-utils/render'
import { screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({
  getPaperAccount: vi.fn(),
  listPaperHoldings: vi.fn(),
  listPaperOrders: vi.fn(),
}))

vi.mock('@/api/paperTrading', () => api)

import { formatDecimalMoney } from '../format-money'
import PaperTradingPage from '../index'

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

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

    expect(api.getPaperAccount).toHaveBeenCalledTimes(2)
    expect(api.listPaperHoldings).toHaveBeenCalledWith({
      account_generation: 3,
    })
    expect(api.listPaperOrders).toHaveBeenCalledWith({
      account_generation: 3,
      limit: 50,
    })
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

  it('keeps successful orders visible when holdings fail', async () => {
    api.listPaperHoldings.mockRejectedValue(new Error('持仓读取失败'))

    renderWithProviders(<PaperTradingPage />)

    expect(await screen.findByText('持仓读取失败')).toBeInTheDocument()
    expect(screen.getByText('已报')).toBeInTheDocument()
    expect(screen.queryByText('还没有成交持仓。可以在对话里让 Agent 买入。')).not.toBeInTheDocument()
  })

  it('keeps successful holdings visible when orders fail', async () => {
    api.listPaperOrders.mockRejectedValue(new Error('订单读取失败'))

    renderWithProviders(<PaperTradingPage />)

    expect(await screen.findByText('订单读取失败')).toBeInTheDocument()
    expect(screen.getByText('200 股')).toBeInTheDocument()
    expect(screen.queryByText('还没有订单。买卖指令会在确认后出现在这里。')).not.toBeInTheDocument()
  })

  it('keeps the whole initial snapshot behind one loading state', async () => {
    const holdings = deferred<never[]>()
    const orders = deferred<never[]>()
    api.listPaperHoldings.mockReturnValue(holdings.promise)
    api.listPaperOrders.mockReturnValue(orders.promise)

    renderWithProviders(<PaperTradingPage />)

    expect(screen.getByText('正在读取模拟账户…')).toBeInTheDocument()
    expect(screen.queryByText(/还没有成交持仓/)).not.toBeInTheDocument()
    expect(screen.queryByText(/还没有订单/)).not.toBeInTheDocument()
  })

  it('refreshes and publishes the account snapshot together', async () => {
    renderWithProviders(<PaperTradingPage />)
    expect(await screen.findAllByText('贵州茅台')).toHaveLength(2)

    const refreshedHoldings = deferred<never[]>()
    api.listPaperHoldings.mockReturnValueOnce(refreshedHoldings.promise)
    api.listPaperOrders.mockResolvedValueOnce([])
    screen.getByRole('button', { name: '刷新账户' }).click()
    expect(await screen.findByText('正在读取持仓…')).toBeInTheDocument()

    refreshedHoldings.resolve([])
    expect(await screen.findByText(/还没有成交持仓/)).toBeInTheDocument()
    expect(screen.queryByText('贵州茅台')).not.toBeInTheDocument()
    expect(api.getPaperAccount).toHaveBeenCalledTimes(4)
  })

  it('retries a reset race and only publishes one account generation', async () => {
    api.getPaperAccount
      .mockResolvedValueOnce({
        id: 'account-1',
        generation: 3,
        initial_cash: '1000000.00',
        available_cash: '800000.00',
        frozen_cash: '0.00',
        status: 'active',
      })
      .mockResolvedValueOnce({
        id: 'account-1',
        generation: 4,
        initial_cash: '500000.00',
        available_cash: '500000.00',
        frozen_cash: '0.00',
        status: 'active',
      })
      .mockResolvedValueOnce({
        id: 'account-1',
        generation: 4,
        initial_cash: '500000.00',
        available_cash: '500000.00',
        frozen_cash: '0.00',
        status: 'active',
      })
      .mockResolvedValueOnce({
        id: 'account-1',
        generation: 4,
        initial_cash: '500000.00',
        available_cash: '500000.00',
        frozen_cash: '0.00',
        status: 'active',
      })
    api.listPaperHoldings
      .mockResolvedValueOnce([
        {
          generation: 3,
          ts_code: '600519.SH',
          name: '旧轮持仓',
          quantity: 100,
          frozen_quantity: 0,
          sellable_quantity: 100,
          average_cost: '1500.0000',
        },
      ])
      .mockResolvedValueOnce([
        {
          generation: 4,
          ts_code: '000001.SZ',
          name: '新轮持仓',
          quantity: 200,
          frozen_quantity: 0,
          sellable_quantity: 200,
          average_cost: '12.0000',
        },
      ])
    api.listPaperOrders
      .mockResolvedValueOnce([
        {
          id: 'old-order',
          account_generation: 3,
          ts_code: '600519.SH',
          name: '旧轮订单',
          side: 'buy',
          order_type: 'limit',
          quantity: 100,
          limit_price: '1500.0000',
          filled_quantity: 0,
          avg_fill_price: null,
          reserved_cash: '150000.00',
          reserved_quantity: 0,
          status: 'open',
          created_at: '2026-07-24T01:00:00Z',
        },
      ])
      .mockResolvedValueOnce([
        {
          id: 'new-order',
          account_generation: 4,
          ts_code: '000001.SZ',
          name: '新轮订单',
          side: 'buy',
          order_type: 'limit',
          quantity: 200,
          limit_price: '12.0000',
          filled_quantity: 0,
          avg_fill_price: null,
          reserved_cash: '2400.00',
          reserved_quantity: 0,
          status: 'open',
          created_at: '2026-07-24T02:00:00Z',
        },
      ])

    renderWithProviders(<PaperTradingPage />)

    expect(await screen.findByText('第 4 轮')).toBeInTheDocument()
    expect(await screen.findByText('新轮持仓')).toBeInTheDocument()
    expect(screen.getByText('新轮订单')).toBeInTheDocument()
    expect(screen.queryByText(/旧轮/)).not.toBeInTheDocument()
    expect(api.listPaperHoldings.mock.calls).toEqual([
      [{ account_generation: 3 }],
      [{ account_generation: 4 }],
    ])
    expect(api.listPaperOrders.mock.calls).toEqual([
      [{ account_generation: 3, limit: 50 }],
      [{ account_generation: 4, limit: 50 }],
    ])
  })

  it.each([
    ['9999999999999999.99', 2, '¥9,999,999,999,999,999.99'],
    ['-12.3', 2, '-¥12.30'],
    ['0', 2, '¥0.00'],
    ['0.5', 4, '¥0.5000'],
    ['not-a-decimal', 2, '—'],
    ['1.234', 2, '—'],
  ])('formats decimal %s exactly without floating point', (value, digits, expected) => {
    expect(formatDecimalMoney(value, digits)).toBe(expected)
  })
})
