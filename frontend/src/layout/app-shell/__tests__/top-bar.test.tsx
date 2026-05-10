import { describe, expect, it } from 'vitest'
import { renderWithProviders } from '@/test-utils/render'
import { TopBar } from '@/layout/app-shell/top-bar'

describe('<TopBar>', () => {
  it('renders product brand text', () => {
    const { getByText } = renderWithProviders(<TopBar />)
    expect(getByText(/financial research/i)).toBeInTheDocument()
  })
})
