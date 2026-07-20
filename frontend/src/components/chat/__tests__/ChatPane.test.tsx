import { describe, expect, it, beforeEach } from 'vitest'
import { act, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'
import { renderWithProviders } from '@/test-utils/render'
import { useLocation } from 'react-router-dom'
import { ChatPane } from '@/components/chat/ChatPane'
import { currentChatActions, currentChatState } from '@/store/current-chat'

const sendPromptMock = vi.fn(async () => {})
const cancelRunMock = vi.fn(async () => {})
const resumeRunMock = vi.fn(async () => {})
let pauseMock: { type: 'approval_request' | 'input_request'; request: Record<string, unknown> } | null = null
let onSessionCreatedMock: ((id: string) => void) | undefined
function LocationProbe({ onPath }: { onPath: (path: string) => void }) {
  onPath(useLocation().pathname)
  return null
}
vi.mock('@/hooks/useRunSSE', () => ({
  useRunSSE: (options: { onSessionCreated?: (id: string) => void }) => {
    onSessionCreatedMock = options.onSessionCreated
    return ({
    sendPrompt: sendPromptMock,
    cancelRun: cancelRunMock,
    resumeRun: resumeRunMock,
    resubmitPrompt: vi.fn(),
    status: 'idle',
    activeRunId: null,
    pause: pauseMock,
  })},
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

describe('<ChatPane> integration with useRunSSE', () => {
  beforeEach(() => {
    sendPromptMock.mockClear()
    cancelRunMock.mockClear()
    resumeRunMock.mockClear()
    pauseMock = null
    currentChatActions.reset()
    currentChatActions.setSession('s1', [])
  })

  it('InputArea send → sendMessage(text) called', async () => {
    const user = userEvent.setup()
    renderWithProviders(<ChatPane sessionId="s1" tenantId="tenant-1" />)
    const ta = screen.getByRole('textbox')
    await user.type(ta, 'hi{Enter}')
    // plain message → forced payload is undefined (slash commands pass a 2nd arg)
    expect(sendPromptMock).toHaveBeenCalledWith('hi')
  })

  it('adopts a lazy Session URL without unmounting the first Run transport', async () => {
    currentChatActions.reset()
    let path = ''
    renderWithProviders(<><ChatPane tenantId="tenant-1" /><LocationProbe onPath={(value) => { path = value }} /></>, { initialRoute: '/chat' })
    expect(onSessionCreatedMock).toBeTypeOf('function')
    act(() => onSessionCreatedMock?.('adopted'))
    await vi.waitFor(() => expect(path).toBe('/chat/adopted'))
  })

  it('renders approval and input pause controls and sends typed resume responses', async () => {
    const user = userEvent.setup()
    pauseMock = { type: 'approval_request', request: { tool: 'trade' } }
    const rendered = renderWithProviders(<ChatPane tenantId="tenant-1" />)
    expect(screen.getByTestId('input-textarea')).toBeDisabled()
    await user.click(screen.getByRole('button', { name: '拒绝' }))
    expect(resumeRunMock).toHaveBeenCalledWith({ approved: false })

    pauseMock = { type: 'input_request', request: { prompt: '补充信息' } }
    rendered.rerender(<ChatPane tenantId="tenant-1" />)
    await user.type(screen.getByLabelText('补充信息'), 'more context')
    await user.click(screen.getByRole('button', { name: '提交补充信息' }))
    expect(resumeRunMock).toHaveBeenLastCalledWith({ text: 'more context' })
  })

  it('allows the first prompt without a pre-created Session', async () => {
    currentChatActions.reset()
    const user = userEvent.setup()
    renderWithProviders(<ChatPane tenantId="tenant-1" />)
    await user.type(screen.getByRole('textbox'), 'first prompt{Enter}')
    expect(sendPromptMock).toHaveBeenCalledWith('first prompt')
  })

  it('Cmd+K while streaming triggers server cancel', async () => {
    currentChatState.streaming_phase = 'writing'
    const user = userEvent.setup()
    renderWithProviders(<ChatPane sessionId="s1" />)
    await user.keyboard('{Meta>}k{/Meta}')
    expect(cancelRunMock).toHaveBeenCalled()
  })
})
