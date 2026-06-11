import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { PlotlySpecRenderer, type PlotlySpec } from '../PlotlySpecRenderer'

// plotly.js-dist-min 在 jsdom 跑不起来 → mock 掉;factory 返回一个占位 Plot 组件。
vi.mock('plotly.js-dist-min', () => ({ default: {} }))
vi.mock('react-plotly.js/factory', () => ({
  default: () => ({ data }: { data: unknown[] }) => (
    <div data-testid="plot" data-traces={String((data ?? []).length)} />
  ),
}))

describe('PlotlySpecRenderer', () => {
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
})
