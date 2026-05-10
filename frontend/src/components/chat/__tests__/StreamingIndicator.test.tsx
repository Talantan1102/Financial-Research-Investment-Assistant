import { render, screen } from '@testing-library/react'
import { describe, expect, it, beforeEach } from 'vitest'
import { StreamingIndicator } from '@/components/chat/StreamingIndicator'
import { currentChatActions, currentChatState } from '@/store/current-chat'

describe('<StreamingIndicator>', () => {
  beforeEach(() => {
    currentChatActions.reset()
  })

  it('hides itself when phase=idle', () => {
    const { container } = render(<StreamingIndicator />)
    expect(container.querySelector('[data-testid="streaming-indicator-bar"]')).toBeNull()
  })

  it('shows "AI 在思考" when phase=thinking', () => {
    currentChatState.streaming_phase = 'thinking'
    render(<StreamingIndicator />)
    expect(screen.getByText(/AI 在思考/)).toBeInTheDocument()
  })

  it('shows "调用工具" when phase=tool', () => {
    currentChatState.streaming_phase = 'tool'
    render(<StreamingIndicator />)
    expect(screen.getByText(/调用工具/)).toBeInTheDocument()
  })

  it('shows "写回答" when phase=writing', () => {
    currentChatState.streaming_phase = 'writing'
    render(<StreamingIndicator />)
    expect(screen.getByText(/写回答/)).toBeInTheDocument()
  })

  it('shows custom label for research_running', () => {
    currentChatState.streaming_phase = 'research_running'
    currentChatState.streaming_phase_label = 'DataCollector 正在跑 5/8 工具'
    render(<StreamingIndicator />)
    expect(screen.getByText(/DataCollector/)).toBeInTheDocument()
  })
})
