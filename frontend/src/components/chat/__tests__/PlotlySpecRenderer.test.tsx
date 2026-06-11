import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { PlotlySpecRenderer } from '../PlotlySpecRenderer'
import type { PlotlySpec } from '@/types/chat'

// plotly.js-dist-min 在 jsdom 跑不起来 → mock 掉;factory 返回一个占位 Plot 组件,
// 并捕获它收到的 data(用于校验"传给 plotly 的是可变深拷,而非只读原对象")。
let receivedData: unknown[] | undefined
vi.mock('plotly.js-dist-min', () => ({ default: {} }))
vi.mock('react-plotly.js/factory', () => ({
  default:
    () =>
    ({ data }: { data: unknown[] }) => {
      receivedData = data
      return <div data-testid="plot" data-traces={String((data ?? []).length)} />
    },
}))

describe('PlotlySpecRenderer', () => {
  beforeEach(() => {
    receivedData = undefined
  })

  it('renders a Plot with the figure traces', () => {
    const spec: PlotlySpec = { type: 'plotly', figure: { data: [{ type: 'scatter' }], layout: {} } }
    render(<PlotlySpecRenderer spec={spec} />)
    expect(screen.getByTestId('plot').getAttribute('data-traces')).toBe('1')
  })

  it('shows a fallback for an invalid spec', () => {
    // @ts-expect-error 故意传非法 spec
    render(<PlotlySpecRenderer spec={{ type: 'plotly' }} />)
    expect(screen.getByText(/plotly spec invalid/i)).toBeInTheDocument()
  })

  // 回归守卫(verify 浏览器实测抓出):figure 来自 valtio store 是 reactive/只读,
  // plotly 绘制时就地 mutate 会抛 "Cannot assign to read only property" 并被 react-plotly
  // 静默吞掉 → 空图。渲染器必须深拷成可变对象再交给 plotly。
  it('passes a mutable clone (not the frozen store object) to plotly', () => {
    const frozenData = Object.freeze([Object.freeze({ type: 'scatter', line: Object.freeze({ color: 'blue' }) })])
    const spec = { type: 'plotly', figure: { data: frozenData, layout: Object.freeze({}) } } as unknown as PlotlySpec
    render(<PlotlySpecRenderer spec={spec} />)
    expect(screen.getByTestId('plot').getAttribute('data-traces')).toBe('1')
    expect(receivedData).toBeDefined()
    // 传给 plotly 的必须是可变深拷:原对象被冻结,克隆后不应再冻结
    expect(Object.isFrozen(receivedData)).toBe(false)
    expect(receivedData).not.toBe(frozenData)
  })
})
