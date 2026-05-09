import { describe, expect, it } from 'vitest'
import { renderWithProviders } from '@/test-utils/render'
import ReportsListPage from '@/pages/reports'

describe('<ReportsListPage>', () => {
  it('renders placeholder text', () => {
    const { getByTestId } = renderWithProviders(<ReportsListPage />)
    expect(getByTestId('reports-list-placeholder')).toBeInTheDocument()
  })
})
