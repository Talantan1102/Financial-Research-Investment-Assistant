import { describe, expect, it, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'
import { renderWithProviders } from '@/test-utils/render'
import { ChatPane } from '@/components/chat/ChatPane'
import { currentChatActions, currentChatState } from '@/store/current-chat'

const sendMessageMock = vi.fn(async () => {})
const abortMock = vi.fn()
vi.mock('@/hooks/useChatSSE', () => ({
  useChatSSE: () => ({ sendMessage: sendMessageMock, abort: abortMock, status: () => 'idle' }),
}))

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

describe('<ChatPane> integration with useChatSSE', () => {
  beforeEach(() => {
    sendMessageMock.mockClear()
    abortMock.mockClear()
    currentChatActions.reset()
    currentChatActions.setSession('s1', [])
  })

  it('InputArea send → sendMessage(text) called', async () => {
    const user = userEvent.setup()
    renderWithProviders(<ChatPane sessionId="s1" />)
    const ta = screen.getByRole('textbox')
    await user.type(ta, 'hi{Enter}')
    expect(sendMessageMock).toHaveBeenCalledWith('hi')
  })

  it('Cmd+K while streaming triggers abort', async () => {
    currentChatState.streaming_phase = 'writing'
    const user = userEvent.setup()
    renderWithProviders(<ChatPane sessionId="s1" />)
    await user.keyboard('{Meta>}k{/Meta}')
    expect(abortMock).toHaveBeenCalled()
  })
})
