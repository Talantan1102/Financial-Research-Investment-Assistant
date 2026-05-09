import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ChartSpecRenderer } from '@/components/chat/ChartSpecRenderer'

vi.mock('echarts-for-react', () => ({
  default: ({ option }: { option: unknown }) => (
    <div data-testid="echarts-mount">{JSON.stringify(option)}</div>
  ),
}))

describe('<ChartSpecRenderer>', () => {
  it('mounts echarts-for-react with parsed option', () => {
    const spec = {
      type: 'echarts' as const,
      option: {
        title: { text: 'ROE 趋势' },
        series: [{ type: 'line', data: [1, 2, 3] }],
      },
    }
    render(<ChartSpecRenderer spec={spec} />)
    expect(screen.getByTestId('echarts-mount')).toHaveTextContent(/ROE 趋势/)
  })

  it('renders fallback box on invalid option', () => {
    render(
      <ChartSpecRenderer
        spec={{ type: 'echarts', option: null as unknown as Record<string, unknown> }}
      />,
    )
    expect(screen.getByText(/chart_spec invalid/i)).toBeInTheDocument()
  })
})
