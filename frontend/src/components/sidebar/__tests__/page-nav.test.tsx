import { describe, expect, it } from 'vitest'
import { renderWithProviders } from '@/test-utils/render'
import { PageNav } from '@/components/sidebar/page-nav'

describe('<PageNav>', () => {
  it('renders links to /research /reports /portfolio /monitoring /knowledge', () => {
    const { getByText } = renderWithProviders(<PageNav />)
    expect(getByText('Research').closest('a')?.getAttribute('href')).toBe('/research')
    expect(getByText('Reports').closest('a')?.getAttribute('href')).toBe('/reports')
    expect(getByText('Portfolio').closest('a')?.getAttribute('href')).toBe('/portfolio')
    expect(getByText('Monitoring').closest('a')?.getAttribute('href')).toBe('/monitoring')
    expect(getByText('Knowledge').closest('a')?.getAttribute('href')).toBe('/knowledge')
  })
})
