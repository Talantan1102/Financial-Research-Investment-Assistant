import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { EmptyState } from '../EmptyState'

describe('<EmptyState>', () => {
  it('renders title + description', () => {
    render(<EmptyState variant="chat-empty" title="Start chat" description="Try asking" />)
    expect(screen.getByText('Start chat')).toBeInTheDocument()
    expect(screen.getByText('Try asking')).toBeInTheDocument()
  })

  it('fires CTA click', async () => {
    const cta = vi.fn()
    const user = userEvent.setup()
    render(
      <EmptyState
        variant="chat-empty"
        title="Empty"
        cta={{ label: 'Start', onClick: cta, primary: true }}
      />
    )
    await user.click(screen.getByRole('button', { name: 'Start' }))
    expect(cta).toHaveBeenCalled()
  })

  it('three variant data-testid', () => {
    const { rerender } = render(<EmptyState variant="chat-empty" title="x" />)
    expect(screen.getByTestId('empty-chat-empty')).toBeInTheDocument()
    rerender(<EmptyState variant="list-empty" title="x" />)
    expect(screen.getByTestId('empty-list-empty')).toBeInTheDocument()
    rerender(<EmptyState variant="search-empty" title="x" />)
    expect(screen.getByTestId('empty-search-empty')).toBeInTheDocument()
  })
})
