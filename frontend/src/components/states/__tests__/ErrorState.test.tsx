import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ErrorState } from '../ErrorState'

describe('<ErrorState>', () => {
  it('renders default title + description', () => {
    render(<ErrorState description="Network error" />)
    expect(screen.getByText('出错了')).toBeInTheDocument()
    expect(screen.getByText('Network error')).toBeInTheDocument()
  })

  it('fires onRetry click', async () => {
    const onRetry = vi.fn()
    const user = userEvent.setup()
    render(<ErrorState onRetry={onRetry} />)
    await user.click(screen.getByRole('button', { name: '重试' }))
    expect(onRetry).toHaveBeenCalled()
  })

  it('fires onReset click', async () => {
    const onReset = vi.fn()
    const user = userEvent.setup()
    render(<ErrorState onReset={onReset} />)
    await user.click(screen.getByRole('button', { name: '重置' }))
    expect(onReset).toHaveBeenCalled()
  })

  it('role alert for screen readers', () => {
    render(<ErrorState />)
    expect(screen.getByRole('alert')).toBeInTheDocument()
  })
})
