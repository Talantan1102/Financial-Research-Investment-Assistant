import {
  getPaperAccount,
  listPaperHoldings,
  listPaperOrders,
  previewPaperOrder,
} from '@/api/paperTrading'
import { beforeEach, describe, expect, it, vi } from 'vitest'

describe('paperTrading API', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    localStorage.setItem('auth', JSON.stringify({ token: 'paper-token' }))
  })

  it('passes the optional AbortSignal to the preview fetch', async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify({ rules_version: 'cn-a-v1' }), {
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    const controller = new AbortController()

    await previewPaperOrder(
      {
        draft: {
          side: 'buy',
          ts_code: '600519.SH',
          name: '贵州茅台',
          quantity: 100,
          order_type: 'limit',
          limit_price: '1500.0000',
        },
      },
      { fetchImpl, signal: controller.signal },
    )

    const [url, init] = fetchImpl.mock.calls[0]
    expect(url).toBe('/api/v0/paper-trading/orders/preview')
    expect(init?.signal).toBe(controller.signal)
    expect(new Headers(init?.headers).get('Authorization')).toBe(
      'Bearer paper-token',
    )
  })

  it('reads account, holdings and bounded order pages with auth', async () => {
    const globalFetch = vi.spyOn(globalThis, 'fetch').mockImplementation(
      async () =>
        new Response(JSON.stringify([]), {
          headers: { 'Content-Type': 'application/json' },
        }),
    )

    await getPaperAccount()
    await listPaperHoldings()
    await listPaperOrders({
      account_generation: 3,
      status: 'open',
      limit: 50,
      offset: 0,
    })

    expect(globalFetch.mock.calls.map(([url]) => url)).toEqual([
      '/api/v0/paper-trading/account',
      '/api/v0/paper-trading/holdings',
      '/api/v0/paper-trading/orders?account_generation=3&status=open&limit=50&offset=0',
    ])
    for (const [, init] of globalFetch.mock.calls) {
      expect(new Headers(init?.headers).get('Authorization')).toBe(
        'Bearer paper-token',
      )
    }
  })

  it('keeps the original injected-fetch signature without touching global fetch', async () => {
    const globalFetch = vi
      .spyOn(globalThis, 'fetch')
      .mockRejectedValue(new Error('global fetch must not be used'))
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify({ rules_version: 'cn-a-v1' }), {
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    await previewPaperOrder(
      {
        draft: {
          side: 'buy',
          ts_code: '600519.SH',
          name: '贵州茅台',
          quantity: 100,
          order_type: 'limit',
          limit_price: '1500.0000',
        },
      },
      fetchImpl,
    )

    expect(fetchImpl).toHaveBeenCalledTimes(1)
    expect(globalFetch).not.toHaveBeenCalled()
  })

  it.each([
    ['string', 'invalid'],
    ['unknown key', { fallback: true }],
    ['invalid fetchImpl', { fetchImpl: 'invalid' }],
    ['invalid signal', { signal: { aborted: false } }],
  ])(
    'rejects %s options instead of silently using global fetch',
    async (_name, invalid) => {
      const globalFetch = vi
        .spyOn(globalThis, 'fetch')
        .mockRejectedValue(new Error('global fetch must not be used'))

      await expect(
        previewPaperOrder(
          {
            draft: {
              side: 'buy',
              ts_code: '600519.SH',
              name: '贵州茅台',
              quantity: 100,
              order_type: 'limit',
              limit_price: '1500.0000',
            },
          },
          invalid as never,
        ),
      ).rejects.toThrow(TypeError)
      expect(globalFetch).not.toHaveBeenCalled()
    },
  )
})
