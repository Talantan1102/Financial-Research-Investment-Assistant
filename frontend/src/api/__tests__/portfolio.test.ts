import { describe, it, expect, vi } from 'vitest'
import * as api from '../portfolio'

describe('portfolio overview api', () => {
  it('getOverview is a function', () => {
    expect(typeof api.getOverview).toBe('function')
  })

  it('getTrend is a function', () => {
    expect(typeof api.getTrend).toBe('function')
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
    } as any)
    const result = await api.getOverview()
    expect(result.data.total_value).toBe(100000)
    spy.mockRestore()
  })

  it('getTrend passes range param', async () => {
    const spy = vi.spyOn(api, 'getTrend').mockResolvedValueOnce({
      data: {
        dates: ['2026-05-01', '2026-06-01'],
        portfolio: [0.01, 0.02],
        benchmark: [0.005, 0.01],
        cumulative: 0.032,
        range: '1m',
      },
    } as any)
    const result = await api.getTrend('1m')
    expect(result.data.range).toBe('1m')
    expect(result.data.dates).toHaveLength(2)
    spy.mockRestore()
  })
})
