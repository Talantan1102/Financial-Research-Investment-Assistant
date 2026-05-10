import { describe, expect, it } from 'vitest'
import { renderWithProviders } from '@/test-utils/render'
import { Sidebar } from '@/layout/app-shell/sidebar'

describe('<Sidebar>', () => {
  it('renders 4 child sections: chat-session-list, new-chat-button, page-nav, user-panel', () => {
    const { getByTestId } = renderWithProviders(<Sidebar />)
    expect(getByTestId('sidebar-new-chat-button')).toBeInTheDocument()
    expect(getByTestId('sidebar-chat-session-list')).toBeInTheDocument()
    expect(getByTestId('sidebar-page-nav')).toBeInTheDocument()
    expect(getByTestId('sidebar-user-panel')).toBeInTheDocument()
  })
})
