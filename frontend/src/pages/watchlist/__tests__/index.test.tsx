import { renderWithProviders } from '@/test-utils/render'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({
  addWatchlistItem: vi.fn(),
  listWatchlist: vi.fn(),
  removeWatchlistItem: vi.fn(),
  updateWatchlistItem: vi.fn(),
}))

vi.mock('@/api/watchlist', () => api)

import WatchlistPage from '../index'

describe('WatchlistPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.listWatchlist.mockResolvedValue([
      {
        id: 'watch-1',
        ts_code: '600519.SH',
        name: '贵州茅台',
        note: '等年报',
        monitoring_enabled: false,
      },
    ])
    api.updateWatchlistItem.mockImplementation(
      async (tsCode: string, changes: Record<string, unknown>) => ({
        id: 'watch-1',
        ts_code: tsCode,
        name: '贵州茅台',
        note: '等年报',
        monitoring_enabled: false,
        ...changes,
      }),
    )
    api.addWatchlistItem.mockImplementation(
      async (payload: Record<string, unknown>) => ({
        id: 'watch-2',
        note: null,
        ...payload,
      }),
    )
    api.removeWatchlistItem.mockResolvedValue({ removed: true })
  })

  it('adds a stock directly with monitoring off by default and blocks double submit', async () => {
    const user = userEvent.setup()
    let resolveAdd: ((value: unknown) => void) | undefined
    api.addWatchlistItem.mockReturnValue(
      new Promise((resolve) => {
        resolveAdd = resolve
      }),
    )
    renderWithProviders(<WatchlistPage />)

    expect(await screen.findByText('贵州茅台')).toBeInTheDocument()
    await user.type(screen.getByLabelText('股票代码'), '000001.SZ')
    await user.type(screen.getByLabelText('股票名称'), '平安银行')
    const add = screen.getByRole('button', { name: '加入自选' })
    await user.click(add)
    expect(add).toBeDisabled()
    fireEvent.click(add)
    expect(api.addWatchlistItem).toHaveBeenCalledOnce()
    expect(api.addWatchlistItem).toHaveBeenCalledWith({
      ts_code: '000001.SZ',
      name: '平安银行',
      monitoring_enabled: false,
    })

    resolveAdd?.({
      id: 'watch-2',
      ts_code: '000001.SZ',
      name: '平安银行',
      note: null,
      monitoring_enabled: false,
    })
    expect(await screen.findByText('平安银行')).toBeInTheDocument()
  })

  it('edits note and monitoring in place, then removes without confirmation', async () => {
    const user = userEvent.setup()
    renderWithProviders(<WatchlistPage />)
    expect(await screen.findByText('贵州茅台')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '编辑 贵州茅台' }))
    const note = screen.getByLabelText('贵州茅台备注')
    await user.clear(note)
    await user.type(note, '关注分红')
    await user.click(screen.getByRole('switch', { name: '贵州茅台监控' }))
    await user.click(screen.getByRole('button', { name: '保存 贵州茅台' }))

    await waitFor(() =>
      expect(api.updateWatchlistItem).toHaveBeenCalledWith('600519.SH', {
        note: '关注分红',
        monitoring_enabled: true,
      }),
    )

    await user.click(screen.getByRole('button', { name: '移除 贵州茅台' }))
    expect(api.removeWatchlistItem).toHaveBeenCalledWith('600519.SH')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    await waitFor(() =>
      expect(screen.queryByText('贵州茅台')).not.toBeInTheDocument(),
    )
  })

  it('ignores a stale list response after a direct mutation', async () => {
    const user = userEvent.setup()
    let resolveList: ((value: unknown) => void) | undefined
    api.listWatchlist.mockReturnValue(
      new Promise((resolve) => {
        resolveList = resolve
      }),
    )
    renderWithProviders(<WatchlistPage />)
    await user.type(screen.getByLabelText('股票代码'), '000001.SZ')
    await user.type(screen.getByLabelText('股票名称'), '平安银行')
    await user.click(screen.getByRole('button', { name: '加入自选' }))
    expect(await screen.findByText('平安银行')).toBeInTheDocument()

    resolveList?.([
      {
        id: 'watch-1',
        ts_code: '600519.SH',
        name: '贵州茅台',
        note: null,
        monitoring_enabled: false,
      },
    ])
    await Promise.resolve()
    expect(screen.getByText('平安银行')).toBeInTheDocument()
    expect(screen.queryByText('贵州茅台')).not.toBeInTheDocument()
  })
})
