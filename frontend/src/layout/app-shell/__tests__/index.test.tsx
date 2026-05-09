import { describe, expect, it } from 'vitest'
import { renderWithProviders } from '@/test-utils/render'
import { AppShell } from '@/layout/app-shell'

describe('<AppShell>', () => {
  it('renders top bar + sidebar (240px) + main outlet content', () => {
    const { getByTestId, getByText } = renderWithProviders(
      <AppShell>
        <div>main content</div>
      </AppShell>,
    )
    expect(getByTestId('app-shell-top-bar')).toBeInTheDocument()
    expect(getByTestId('app-shell-sidebar')).toBeInTheDocument()
    expect(getByText('main content')).toBeInTheDocument()
  })
})
