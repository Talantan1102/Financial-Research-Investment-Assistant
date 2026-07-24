import { describe, expect, it, beforeEach } from 'vitest'
import { act, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'
import { renderWithProviders } from '@/test-utils/render'
import { useLocation } from 'react-router-dom'
import { ChatPane } from '@/components/chat/ChatPane'
import { currentChatActions, currentChatState } from '@/store/current-chat'
import { previewPaperOrder } from '@/api/paperTrading'

vi.mock('@/api/paperTrading', () => ({
  previewPaperOrder: vi.fn(),
}))

const sendPromptMock = vi.fn(async () => ({ ok: true as const }))
const cancelRunMock = vi.fn(async () => ({ ok: true as const }))
const resumeRunMock = vi.fn(async () => ({ ok: true as const }))
const resubmitPromptMock = vi.fn(async () => ({ ok: true as const }))
let pauseMock: {
  id: string
  type: 'approval_request' | 'input_request'
  request: Record<string, unknown>
} | null = null
let revisionsMock: Array<{
  id: string
  replaces_run_id: string | null
  status: string
  prompt: string
  final_message_summary: string | null
}> = []
let latestRunIdMock: string | null = null
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
    resubmitPrompt: resubmitPromptMock,
    status: 'idle',
    activeRunId: null,
    pause: pauseMock,
    revisions: revisionsMock,
    latestRunId: latestRunIdMock,
    commandPending: false,
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
    resubmitPromptMock.mockClear()
    pauseMock = null
    revisionsMock = []
    latestRunIdMock = null
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
    pauseMock = {
      id: 'pause-approval',
      type: 'approval_request',
      request: {
        tool_calls: [
          { id: 'call-1', name: 'place_order', arguments: { symbol: '600000', quantity: 100 } },
        ],
        execution_bindings: [
          {
            execution_id: 'execution-7', semantic_key: 'send_notice:abc',
            tool_call: { id: 'call-2', name: 'send_notice', arguments: { channel: 'email' } },
          },
        ],
      },
    }
    const rendered = renderWithProviders(<ChatPane tenantId="tenant-1" />)
    expect(screen.getByTestId('input-textarea')).toBeDisabled()
    expect(screen.getByText('place_order')).toBeInTheDocument()
    expect(screen.getByText(/"symbol": "600000"/)).toBeInTheDocument()
    expect(screen.getByText('send_notice')).toBeInTheDocument()
    expect(screen.getByText(/execution-7/)).toBeInTheDocument()
    expect(screen.getByText(/send_notice:abc/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '全部批准' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '全部拒绝' }))
    expect(resumeRunMock).toHaveBeenCalledWith({ approved: false })

    pauseMock = {
      id: 'pause-input',
      type: 'input_request',
      request: {
        question: '<img src=x onerror="globalThis.pwned=true">请输入成本价？',
        message: 'lower priority',
      },
    }
    rendered.rerender(<ChatPane tenantId="tenant-1" />)
    expect(screen.getByText(/请输入成本价/)).toBeInTheDocument()
    expect(document.querySelector('img')).toBeNull()
    await user.type(screen.getByLabelText('补充信息'), 'more context')
    await user.click(screen.getByRole('button', { name: '提交补充信息' }))
    expect(resumeRunMock).toHaveBeenLastCalledWith({ text: 'more context' })
  })

  it('renders one editable paper write as a dedicated card and keeps ordinary approvals generic', async () => {
    const user = userEvent.setup()
    vi.mocked(previewPaperOrder).mockResolvedValue({
      draft: {
        side: 'buy', ts_code: '600519.SH', name: '贵州茅台', quantity: 100,
        order_type: 'limit', limit_price: '1500.0000',
      },
      quote: {
        ts_code: '600519.SH', name: '贵州茅台', price: '1500.0000',
        timestamp: '2026-07-23T02:00:00Z', source: 'test', is_suspended: false,
        bid1: null, ask1: null, upper_limit: null, lower_limit: null,
      },
      estimated_gross: '150000.00',
      estimated_fees: { commission: '45.00', stamp_duty: '0.00', transfer_fee: '1.50', total: '46.50' },
      estimated_cash_required: '150046.50',
      available_cash: '1000000.00',
      sellable_quantity: 0,
      market_phase: 'continuous',
      rules_version: 'cn-a-v1',
    })
    pauseMock = {
      id: 'pause-paper',
      type: 'approval_request',
      request: {
        tool_calls: [{
          id: 'trade-1',
          name: 'place_paper_order',
          arguments: {
            side: 'buy', ts_code: '600519.SH', name: '贵州茅台', quantity: 100,
            order_type: 'limit', limit_price: '1500.0000',
          },
        }],
        editable_tool_call_ids: ['trade-1'],
      },
    }
    const rendered = renderWithProviders(<ChatPane tenantId="tenant-1" />)
    expect(screen.getByRole('region', { name: '模拟交易审批' })).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: '审批请求' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '预览交易' }))
    await user.click(await screen.findByRole('button', { name: '确认买入' }))
    expect(resumeRunMock).toHaveBeenCalledWith({
      approved: true,
      edited_arguments: {
        'trade-1': expect.objectContaining({ quantity: 100, limit_price: '1500.0000' }),
      },
    })

    pauseMock = {
      id: 'pause-generic',
      type: 'approval_request',
      request: {
        tool_calls: [{ id: 'high-1', name: 'send_notice', arguments: { channel: 'email' } }],
        editable_tool_call_ids: ['high-1'],
      },
    }
    rendered.rerender(<ChatPane tenantId="tenant-1" />)
    expect(screen.queryByRole('region', { name: '模拟交易审批' })).not.toBeInTheDocument()
    expect(screen.getByRole('region', { name: '审批请求' })).toBeInTheDocument()
  })

  it('allows the first prompt without a pre-created Session', async () => {
    currentChatActions.reset()
    const user = userEvent.setup()
    renderWithProviders(<ChatPane tenantId="tenant-1" />)
    await user.type(screen.getByRole('textbox'), 'first prompt{Enter}')
    expect(sendPromptMock).toHaveBeenCalledWith('first prompt')
  })

  it('expands immutable revision history and retries only from the latest Run', async () => {
    const user = userEvent.setup()
    revisionsMock = [
      { id: 'run-a', replaces_run_id: null, status: 'completed', prompt: 'prompt A', final_message_summary: 'answer A' },
      { id: 'run-b', replaces_run_id: 'run-a', status: 'failed', prompt: 'prompt B', final_message_summary: null },
    ]
    latestRunIdMock = 'run-b'
    renderWithProviders(<ChatPane sessionId="s1" tenantId="tenant-1" />)

    await user.click(screen.getByText('修订历史'))
    expect(screen.getByText('prompt A')).toBeInTheDocument()
    expect(screen.getByText('answer A')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: '修改后重试' })).toHaveLength(1)
    await user.click(screen.getByRole('button', { name: '修改后重试' }))
    const editor = screen.getByRole('textbox', { name: '修改提示词' })
    expect(editor).toHaveValue('prompt B')
    await user.clear(editor)
    await user.type(editor, 'prompt C')
    await user.click(screen.getByRole('button', { name: '提交新修订' }))

    expect(resubmitPromptMock).toHaveBeenCalledWith('prompt C', 'run-b')
    expect(sendPromptMock).not.toHaveBeenCalled()
  })

  it('keeps revision and ask-user drafts when their command fails', async () => {
    const user = userEvent.setup()
    revisionsMock = [
      { id: 'run-b', replaces_run_id: null, status: 'failed', prompt: 'prompt B', final_message_summary: null },
    ]
    latestRunIdMock = 'run-b'
    resubmitPromptMock.mockResolvedValueOnce({ ok: false })
    const rendered = renderWithProviders(<ChatPane sessionId="s1" tenantId="tenant-1" />)
    await user.click(screen.getByText('prompt B').closest('details')!.querySelector('summary')!)
    await user.click(screen.getByText('prompt B').closest('li')!.querySelector('button')!)
    const editor = document.querySelectorAll('textarea')[1]
    await user.clear(editor)
    await user.type(editor, 'retry draft')
    await user.click(editor.closest('div')!.querySelector('button')!)
    expect(editor).toHaveValue('retry draft')

    pauseMock = { id: 'pause-input', type: 'input_request', request: { question: 'more?' } }
    resumeRunMock.mockResolvedValueOnce({ ok: false })
    rendered.rerender(<ChatPane sessionId="s1" tenantId="tenant-1" />)
    const answer = Array.from(document.querySelectorAll('textarea')).at(-1)!
    await user.type(answer, 'keep me')
    await user.click(answer.closest('div')!.querySelector('button')!)
    expect(answer).toHaveValue('keep me')
  })

  it('Cmd+K while streaming triggers server cancel', async () => {
    currentChatState.streaming_phase = 'writing'
    const user = userEvent.setup()
    renderWithProviders(<ChatPane sessionId="s1" />)
    await user.keyboard('{Meta>}k{/Meta}')
    expect(cancelRunMock).toHaveBeenCalled()
  })
})
