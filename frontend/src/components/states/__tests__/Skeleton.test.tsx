import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Skeleton } from '../Skeleton'

describe('<Skeleton>', () => {
  it('renders 3 bars by default', () => {
    const { container } = render(<Skeleton variant="list" />)
    expect(container.querySelectorAll('[data-testid="skeleton-bar"]').length).toBe(3)
  })

  it('respects count', () => {
    const { container } = render(<Skeleton variant="list" count={5} />)
    expect(container.querySelectorAll('[data-testid="skeleton-bar"]').length).toBe(5)
  })

  it('three variants render', () => {
    const { rerender, container } = render(<Skeleton variant="list" />)
    expect(container.querySelector('[data-testid="skeleton-list"]')).toBeInTheDocument()
    rerender(<Skeleton variant="message" />)
    expect(container.querySelector('[data-testid="skeleton-message"]')).toBeInTheDocument()
    rerender(<Skeleton variant="card" />)
    expect(container.querySelector('[data-testid="skeleton-card"]')).toBeInTheDocument()
  })
})
