import { describe, it, expect, vi } from 'vitest'
import * as api from '../portfolio'

describe('portfolio overview api', () => {
  it('getOverview is a function', () => {
    expect(typeof api.getOverview).toBe('function')
  })

  it('getOverview hits /portfolio/overview', async () => {
    const spy = vi.spyOn(api, 'getOverview').mockResolvedValueOnce({
      data: {
        total_value: 100000,
        today_pct: 0.5,
        ytd_pct: 12.0,
        attribution: {
          total_pct: 0.5,
          by_class: { stock: 0.5 },
          stock_breakdown: { market: 0.2, sector_excess: 0.1, idiosyncratic: 0.2 },
          contributions: [],
        },
        structure: { by_class: { stock: 0.8 }, by_sector: { 科技: 0.4 }, as_of: '2026-06-01' },
        narrative: '今天涨了。',
      },
    } as unknown as Awaited<ReturnType<typeof api.getOverview>>)
    const result = await api.getOverview()
    expect(result.data.total_value).toBe(100000)
    spy.mockRestore()
  })
})
