import { describe, expect, it } from 'vitest'
import { renderWithProviders } from '@/test-utils/render'

describe('renderWithProviders', () => {
  it('mounts a component inside MemoryRouter + ConfigProvider', () => {
    const { getByText } = renderWithProviders(<div>hello</div>)
    expect(getByText('hello')).toBeInTheDocument()
  })

  it('honors initial route', () => {
    const { container } = renderWithProviders(<div>route ok</div>, {
      initialRoute: '/chat/abc',
    })
    expect(container.textContent).toContain('route ok')
  })
})
