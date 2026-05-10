import { describe, expect, it } from 'vitest'
import { renderWithProviders } from '@/test-utils/render'
import { UserPanel } from '@/components/sidebar/user-panel'

describe('<UserPanel>', () => {
  it('renders anonymous when not logged in', () => {
    const { getByText, getByTestId } = renderWithProviders(<UserPanel />)
    expect(getByTestId('sidebar-user-panel')).toBeInTheDocument()
    expect(getByText(/anonymous/i)).toBeInTheDocument()
  })
})
