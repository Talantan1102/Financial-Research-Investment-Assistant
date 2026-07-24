import {
  addWatchlistItem,
  listWatchlist,
  removeWatchlistItem,
  updateWatchlistItem,
} from '@/api/watchlist'
import { beforeEach, describe, expect, it, vi } from 'vitest'

describe('watchlist API', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    localStorage.setItem('auth', JSON.stringify({ token: 'watch-token' }))
  })

  it('uses authenticated REST operations without a confirmation endpoint', async () => {
    const globalFetch = vi.spyOn(globalThis, 'fetch').mockImplementation(
      async () =>
        new Response(JSON.stringify({ removed: true }), {
          headers: { 'Content-Type': 'application/json' },
        }),
    )

    await listWatchlist()
    await addWatchlistItem({
      ts_code: '600519.SH',
      name: '贵州茅台',
      monitoring_enabled: false,
    })
    await updateWatchlistItem('600519.SH', {
      note: '等年报',
      monitoring_enabled: true,
    })
    await removeWatchlistItem('600519.SH')

    expect(
      globalFetch.mock.calls.map(([url, init]) => [url, init?.method ?? 'GET']),
    ).toEqual([
      ['/api/v0/watchlist', 'GET'],
      ['/api/v0/watchlist', 'POST'],
      ['/api/v0/watchlist/600519.SH', 'PATCH'],
      ['/api/v0/watchlist/600519.SH', 'DELETE'],
    ])
    for (const [, init] of globalFetch.mock.calls) {
      expect(new Headers(init?.headers).get('Authorization')).toBe(
        'Bearer watch-token',
      )
    }
  })

  it('surfaces a backend detail message', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ detail: '股票代码不合法' }), {
        status: 422,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    await expect(listWatchlist()).rejects.toThrow('股票代码不合法')
  })
})
