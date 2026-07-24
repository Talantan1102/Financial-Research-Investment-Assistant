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

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise
  })
  return { promise, resolve }
}

describe('WatchlistPage', () => {
  beforeEach(() => {
    vi.resetAllMocks()
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
    expect(
      screen.getByText('持仓股票始终监控；开关只控制自选股来源。'),
    ).toBeInTheDocument()
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

  it('locks add while delete for the same code is pending, then releases it', async () => {
    const user = userEvent.setup()
    const removing = deferred<{ removed: boolean }>()
    api.removeWatchlistItem.mockReturnValue(removing.promise)
    renderWithProviders(<WatchlistPage />)
    expect(await screen.findByText('贵州茅台')).toBeInTheDocument()

    await user.type(screen.getByLabelText('股票代码'), '600519.SH')
    await user.type(screen.getByLabelText('股票名称'), '贵州茅台')
    await user.click(screen.getByRole('button', { name: '移除 贵州茅台' }))
    expect(screen.getByRole('button', { name: '加入自选' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: '加入自选' }))

    expect(api.addWatchlistItem).not.toHaveBeenCalled()
    removing.resolve({ removed: true })
    await waitFor(() =>
      expect(screen.getByRole('button', { name: '加入自选' })).toBeEnabled(),
    )
    await user.click(screen.getByRole('button', { name: '加入自选' }))
    expect(api.addWatchlistItem).toHaveBeenCalledOnce()
  })

  it('blocks remove while save for the same code is pending', async () => {
    const user = userEvent.setup()
    const updating = deferred<Record<string, unknown>>()
    api.updateWatchlistItem.mockReturnValue(updating.promise)
    renderWithProviders(<WatchlistPage />)
    expect(await screen.findByText('贵州茅台')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '编辑 贵州茅台' }))
    await user.click(screen.getByRole('button', { name: '保存 贵州茅台' }))
    expect(screen.getByRole('button', { name: '移除 贵州茅台' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: '移除 贵州茅台' }))
    expect(api.removeWatchlistItem).not.toHaveBeenCalled()

    updating.resolve({
      id: 'watch-1',
      ts_code: '600519.SH',
      name: '贵州茅台',
      note: '等年报',
      monitoring_enabled: false,
    })
    expect(await screen.findByText('贵州茅台')).toBeInTheDocument()
  })

  it('blocks save in the same tick after remove starts', async () => {
    const user = userEvent.setup()
    const removing = deferred<{ removed: boolean }>()
    api.removeWatchlistItem.mockReturnValue(removing.promise)
    renderWithProviders(<WatchlistPage />)
    expect(await screen.findByText('贵州茅台')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '编辑 贵州茅台' }))
    fireEvent.click(screen.getByRole('button', { name: '移除 贵州茅台' }))
    fireEvent.click(screen.getByRole('button', { name: '保存 贵州茅台' }))
    expect(api.updateWatchlistItem).not.toHaveBeenCalled()
    removing.resolve({ removed: true })
    await waitFor(() =>
      expect(screen.queryByText('贵州茅台')).not.toBeInTheDocument(),
    )
  })

  it('does not show an empty state when the initial list fails', async () => {
    api.listWatchlist.mockRejectedValue(new Error('列表读取失败'))
    renderWithProviders(<WatchlistPage />)

    expect(await screen.findByRole('alert')).toHaveTextContent('列表读取失败')
    expect(screen.queryByText(/还没有自选股/)).not.toBeInTheDocument()
  })

  it('reloads the failed code from the server before unlocking it', async () => {
    const user = userEvent.setup()
    api.listWatchlist
      .mockResolvedValueOnce([
        {
          id: 'watch-1',
          ts_code: '600519.SH',
          name: '贵州茅台',
          note: '等年报',
          monitoring_enabled: false,
        },
      ])
      .mockResolvedValueOnce([])
    api.updateWatchlistItem.mockRejectedValue(new Error('记录已不存在'))
    renderWithProviders(<WatchlistPage />)
    expect(await screen.findByText('贵州茅台')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '编辑 贵州茅台' }))
    await user.click(screen.getByRole('button', { name: '保存 贵州茅台' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('记录已不存在')
    await waitFor(() => expect(api.listWatchlist).toHaveBeenCalledTimes(2))
    expect(screen.queryByText('贵州茅台')).not.toBeInTheDocument()
  })

  it('does not close stock B draft when stock A save returns', async () => {
    const user = userEvent.setup()
    const updatingA = deferred<Record<string, unknown>>()
    api.listWatchlist.mockResolvedValue([
      {
        id: 'watch-1',
        ts_code: '600519.SH',
        name: '贵州茅台',
        note: 'A备注',
        monitoring_enabled: false,
      },
      {
        id: 'watch-2',
        ts_code: '000001.SZ',
        name: '平安银行',
        note: 'B备注',
        monitoring_enabled: false,
      },
    ])
    api.updateWatchlistItem.mockReturnValue(updatingA.promise)
    renderWithProviders(<WatchlistPage />)
    expect(await screen.findByText('贵州茅台')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '编辑 贵州茅台' }))
    await user.click(screen.getByRole('button', { name: '保存 贵州茅台' }))
    await user.click(screen.getByRole('button', { name: '编辑 平安银行' }))
    expect(screen.getByLabelText('平安银行备注')).toHaveValue('B备注')

    updatingA.resolve({
      id: 'watch-1',
      ts_code: '600519.SH',
      name: '贵州茅台',
      note: 'A备注',
      monitoring_enabled: false,
    })
    await waitFor(() =>
      expect(screen.getByLabelText('平安银行备注')).toHaveValue('B备注'),
    )
  })

  it('allows mutations for different stock codes to run in parallel', async () => {
    const user = userEvent.setup()
    const first = deferred<{ removed: boolean }>()
    const second = deferred<{ removed: boolean }>()
    api.listWatchlist.mockResolvedValue([
      {
        id: 'watch-1',
        ts_code: '600519.SH',
        name: '贵州茅台',
        note: null,
        monitoring_enabled: false,
      },
      {
        id: 'watch-2',
        ts_code: '000001.SZ',
        name: '平安银行',
        note: null,
        monitoring_enabled: false,
      },
    ])
    api.removeWatchlistItem.mockImplementation((tsCode: string) =>
      tsCode === '600519.SH' ? first.promise : second.promise,
    )
    renderWithProviders(<WatchlistPage />)
    expect(await screen.findByText('贵州茅台')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '移除 贵州茅台' }))
    await user.click(screen.getByRole('button', { name: '移除 平安银行' }))

    expect(api.removeWatchlistItem).toHaveBeenCalledTimes(2)
    first.resolve({ removed: true })
    second.resolve({ removed: true })
  })
})
