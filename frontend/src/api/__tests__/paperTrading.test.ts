import { previewPaperOrder } from '@/api/paperTrading'
import { beforeEach, describe, expect, it, vi } from 'vitest'

describe('paperTrading API', () => {
  beforeEach(() => {
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
})
