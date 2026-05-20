import { describe, expect, it } from 'vitest'
import { renderWithProviders } from '@/test-utils/render'
import { PageNav } from '@/components/sidebar/page-nav'

describe('<PageNav>', () => {
  it('renders links to /research /reports /portfolio /monitoring /knowledge', () => {
    const { getByText } = renderWithProviders(<PageNav />)
    expect(getByText('研报中心').closest('a')?.getAttribute('href')).toBe('/research')
    expect(getByText('报告中心').closest('a')?.getAttribute('href')).toBe('/reports')
    expect(getByText('持仓').closest('a')?.getAttribute('href')).toBe('/portfolio')
    expect(getByText('监控告警').closest('a')?.getAttribute('href')).toBe('/monitoring')
    expect(getByText('知识库').closest('a')?.getAttribute('href')).toBe('/knowledge')
  })
})
