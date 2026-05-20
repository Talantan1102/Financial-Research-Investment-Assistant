import { describe, expect, it } from 'vitest'
import { renderWithProviders } from '@/test-utils/render'
import { TopBar } from '@/layout/app-shell/top-bar'

describe('<TopBar>', () => {
  it('renders product brand text', () => {
    const { getByTestId } = renderWithProviders(<TopBar />)
    expect(getByTestId('app-topbar')).toBeInTheDocument()
  })

  it('renders 我的画像 link pointing to /memory#persona', () => {
    const { getByRole } = renderWithProviders(<TopBar />)
    const link = getByRole('link', { name: /我的画像/ })
    expect(link).toBeInTheDocument()
    expect(link).toHaveAttribute('href', '/memory#persona')
  })
})
