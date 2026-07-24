import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, beforeEach } from 'vitest'
import { CostMeter } from '@/components/chat/CostMeter'
import { currentChatActions, currentChatState } from '@/store/current-chat'

describe('<CostMeter>', () => {
  beforeEach(() => {
    currentChatActions.reset()
  })

  it('shows $0.00 by default', () => {
    render(<CostMeter />)
    expect(screen.getByText(/\$0\.0/)).toBeInTheDocument()
  })

  it('shows total in collapsed view', () => {
    currentChatState.cost_breakdown = { chat_usd: 0.012, research_usd: 0.087, total_usd: 0.099 }
    currentChatState.cost_so_far = 0.099
    render(<CostMeter />)
    expect(screen.getByText(/\$0\.099/)).toBeInTheDocument()
  })

  it('expands to show chat + research breakdown', async () => {
    currentChatState.cost_breakdown = { chat_usd: 0.012, research_usd: 0.087, total_usd: 0.099 }
    const user = userEvent.setup()
    render(<CostMeter />)
    await user.click(screen.getByRole('button', { name: /详情|breakdown/i }))
    expect(screen.getByText(/Chat:/)).toBeInTheDocument()
    expect(screen.getByText(/Research:/)).toBeInTheDocument()
  })
})
