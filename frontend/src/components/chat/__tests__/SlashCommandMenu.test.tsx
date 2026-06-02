import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { SlashCommandMenu } from '@/components/chat/SlashCommandMenu'

describe('<SlashCommandMenu>', () => {
  it('renders all commands when query is just "/"', () => {
    render(<SlashCommandMenu open query="/" onSelect={vi.fn()} />)
    expect(screen.getByText('/quote')).toBeInTheDocument()
    expect(screen.getByText('/kb')).toBeInTheDocument()
  })

  it('filters by typed prefix', () => {
    render(<SlashCommandMenu open query="/qu" onSelect={vi.fn()} />)
    expect(screen.getByText('/quote')).toBeInTheDocument()
    expect(screen.queryByText('/kb')).not.toBeInTheDocument()
  })

  it('calls onSelect with the alias when an item is clicked', async () => {
    const onSelect = vi.fn()
    render(<SlashCommandMenu open query="/qu" onSelect={onSelect} />)
    await userEvent.click(screen.getByText('/quote'))
    expect(onSelect).toHaveBeenCalledWith('/quote')
  })

  it('renders nothing when open=false', () => {
    const { container } = render(<SlashCommandMenu open={false} query="/" onSelect={vi.fn()} />)
    expect(container).toBeEmptyDOMElement()
  })
})
