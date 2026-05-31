import { describe, expect, it } from 'vitest'
import { renderWithProviders } from '@/test-utils/render'
import { Sidebar } from '@/layout/app-shell/sidebar'

describe('<Sidebar>', () => {
  it('renders sidebar wrapper with data-testid', () => {
    const { getByTestId } = renderWithProviders(<Sidebar />)
    expect(getByTestId('app-sidebar')).toBeInTheDocument()
  })

  it('renders search input', () => {
    const { getByTestId } = renderWithProviders(<Sidebar />)
    expect(getByTestId('sidebar-search-input')).toBeInTheDocument()
  })

  it('renders main sections: chat-session-list, new-chat-button, history-toggle, user-panel', () => {
    const { getByTestId } = renderWithProviders(<Sidebar />)
    expect(getByTestId('sidebar-new-chat-button')).toBeInTheDocument()
    expect(getByTestId('sidebar-chat-session-list')).toBeInTheDocument()
    expect(getByTestId('sidebar-history-toggle')).toBeInTheDocument()
    expect(getByTestId('sidebar-user-panel')).toBeInTheDocument()
  })
})
