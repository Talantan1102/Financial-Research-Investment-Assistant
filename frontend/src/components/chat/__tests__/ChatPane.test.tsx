import { describe, expect, it, beforeEach } from 'vitest'
import { renderWithProviders } from '@/test-utils/render'
import { ChatPane } from '@/components/chat/ChatPane'
import { currentChatActions } from '@/store/current-chat'

describe('<ChatPane>', () => {
  beforeEach(() => currentChatActions.reset())

  it('renders MessageList region + InputArea region + CostMeter', () => {
    const { getByRole, getByTestId } = renderWithProviders(<ChatPane />)
    expect(getByRole('region', { name: /messages/i })).toBeInTheDocument()
    expect(getByRole('region', { name: /input/i })).toBeInTheDocument()
    expect(getByTestId('cost-meter')).toBeInTheDocument()
  })

  it('renders empty-state hint when no messages', () => {
    currentChatActions.setSession('s1', [])
    const { getByText } = renderWithProviders(<ChatPane />)
    expect(getByText((text) => text.includes('开始一个新对话'))).toBeInTheDocument()
  })
})
