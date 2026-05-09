import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, beforeEach, vi } from 'vitest'
import { EscalationConfirmDialog } from '@/components/escalation/EscalationConfirmDialog'
import { escalationActions, escalationState } from '@/store/escalation'
import type { EscalationPacket } from '@/types/escalation'

function makeDraft(): EscalationPacket {
  return {
    explicit_task: {
      raw_last_user_turn: '帮我评估 ICBC',
      extracted_intent: '投资尽调',
      target_ts_code: '601398.SH',
      target_entity_name: '工商银行',
      user_extra_message: null,
    },
    chat_derived_signals: {
      entities: [],
      preferences: [],
      open_questions: [],
      inferred_persona: null,
      extraction_confidence: 0.8,
    },
    known_facts: {
      tool_results: [
        {
          tool_name: 'get_stock_quote',
          tool_args: { ts_code: '601398.SH' },
          result_summary: 'price 5.43',
          cached_at: '2026-05-09T00:00:00Z',
          cache_id: 'k1',
        },
      ],
    },
    session_metadata: {
      chat_session_id: 'c1',
      chat_turn_count: 4,
      chat_history_summary: null,
      user_confirmed_at: '',
      user_edits: [],
    },
    missing_field_hints: [],
  }
}

describe('<EscalationConfirmDialog>', () => {
  beforeEach(() => {
    escalationActions.reset()
    escalationState.dialog_open = true
    escalationState.session_id = 'c1'
    escalationState.packet_draft = makeDraft()
    escalationState.phase = 'draft'
  })

  it('renders 4 sub-forms when packet_draft loaded', () => {
    render(<EscalationConfirmDialog />)
    expect(screen.getByText(/Explicit Task/)).toBeInTheDocument()
    expect(screen.getByText(/Chat Derived Signals/)).toBeInTheDocument()
    expect(screen.getByText(/Known Facts/)).toBeInTheDocument()
    expect(screen.getByText(/Session Metadata/)).toBeInTheDocument()
  })

  it('shows extracted_intent value in ExplicitTask form', () => {
    render(<EscalationConfirmDialog />)
    expect(screen.getByDisplayValue('投资尽调')).toBeInTheDocument()
  })

  it('lists tool_results read-only in KnownFacts form', () => {
    render(<EscalationConfirmDialog />)
    expect(screen.getByText(/get_stock_quote/)).toBeInTheDocument()
    expect(screen.getByText(/price 5\.43/)).toBeInTheDocument()
  })

  it('hides itself when dialog_open=false', () => {
    escalationState.dialog_open = false
    render(<EscalationConfirmDialog />)
    expect(screen.queryByRole('dialog')).toBeNull()
  })
})

import { waitFor } from '@testing-library/react'
import { setConfirmEscalationFn } from '@/store/escalation'
import type { ConfirmEscalationArgs, ConfirmEscalationResult } from '@/api/chatApi'

describe('<EscalationConfirmDialog> Confirm flow', () => {
  beforeEach(() => {
    escalationActions.reset()
    escalationState.dialog_open = true
    escalationState.session_id = 'c1'
    escalationState.packet_draft = makeDraft()
    escalationState.phase = 'draft'
  })

  it('Confirm button calls chatApi.confirmEscalation with packet + user_edits', async () => {
    const spy = vi.fn<[ConfirmEscalationArgs], Promise<ConfirmEscalationResult>>().mockResolvedValue({ ok: true })
    setConfirmEscalationFn(spy)
    escalationState.user_edits = [
      {
        field_path: 'explicit_task.extracted_intent',
        llm_value: '投资尽调',
        user_value: '尽调 + 风险评估',
        edit_type: 'modify',
      },
    ]
    const user = userEvent.setup()
    render(<EscalationConfirmDialog />)
    await user.click(screen.getByTestId('escalation-confirm-btn'))
    await waitFor(() => expect(spy).toHaveBeenCalled())
    const arg = spy.mock.calls[0][0]
    expect(arg.session_id).toBe('c1')
    expect(arg.packet.session_metadata.user_edits.length).toBe(1)
  })

  it('shows 提交中 while in flight', async () => {
    let resolve: ((v: ConfirmEscalationResult) => void) | null = null
    const spy = vi.fn<[ConfirmEscalationArgs], Promise<ConfirmEscalationResult>>().mockImplementation(
      () =>
        new Promise<ConfirmEscalationResult>((r) => {
          resolve = r
        }),
    )
    setConfirmEscalationFn(spy)
    const user = userEvent.setup()
    render(<EscalationConfirmDialog />)
    await user.click(screen.getByTestId('escalation-confirm-btn'))
    await waitFor(() => expect(screen.getByText(/提交中/)).toBeInTheDocument())
    resolve?.({ ok: true })
  })
})

describe('<EscalationConfirmDialog> ChatDerivedSignals + SessionMetadata', () => {
  beforeEach(() => {
    escalationActions.reset()
    escalationState.dialog_open = true
    escalationState.session_id = 'c1'
    escalationState.phase = 'draft'
  })

  it('renders entities[] with name + ts_code + role tags', async () => {
    escalationState.packet_draft = {
      ...makeDraft(),
      chat_derived_signals: {
        entities: [
          {
            name: '工商银行',
            ts_code: '601398.SH',
            role: 'primary_target',
            mention_turn_indices: [1, 3],
          },
          {
            name: '招商银行',
            ts_code: '600036.SH',
            role: 'comparative_target',
            mention_turn_indices: [5],
          },
        ],
        preferences: [
          { text: '关注分红', category: 'focus_metric', confidence: 0.7 },
        ],
        open_questions: ['ROE 趋势如何'],
        inferred_persona: '稳健银行投资者',
        extraction_confidence: 0.82,
      },
    }
    const user = userEvent.setup()
    render(<EscalationConfirmDialog />)
    await user.click(screen.getByText(/对话信号/))
    expect(screen.getByText(/工商银行/)).toBeInTheDocument()
    expect(screen.getByText(/comparative_target/)).toBeInTheDocument()
    expect(screen.getByText(/关注分红/)).toBeInTheDocument()
    expect(screen.getByText(/ROE 趋势如何/)).toBeInTheDocument()
  })

  it('SessionMetadata form shows turn_count + history_summary read-only', async () => {
    escalationState.packet_draft = {
      ...makeDraft(),
      session_metadata: {
        chat_session_id: 'c1',
        chat_turn_count: 7,
        chat_history_summary: '4 轮关于工商银行 + 2 轮招商银行',
        user_confirmed_at: '',
        user_edits: [],
      },
    }
    const user = userEvent.setup()
    render(<EscalationConfirmDialog />)
    await user.click(screen.getByText(/Session/))
    expect(screen.getByText(/4 轮关于工商银行/)).toBeInTheDocument()
  })
})
