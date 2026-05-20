import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { LoadingDots } from '../LoadingDots'

describe('<LoadingDots>', () => {
  it('renders 3 dot spans', () => {
    const { container } = render(<LoadingDots />)
    const dots = container.querySelectorAll('span span')
    expect(dots.length).toBeGreaterThanOrEqual(3)
  })

  it('respects role status for screen readers', () => {
    const { getByRole } = render(<LoadingDots />)
    expect(getByRole('status')).toBeInTheDocument()
  })
})
