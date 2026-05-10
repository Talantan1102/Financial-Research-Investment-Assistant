import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { MissingFieldBanner } from '@/components/escalation/MissingFieldBanner'
import type { MissingFieldHint } from '@/types/escalation'

describe('<MissingFieldBanner>', () => {
  it('renders nothing for empty hints', () => {
    const { container } = render(<MissingFieldBanner hints={[]} />)
    expect(container.firstChild).toBeNull()
  })

  it('renders ⚠️ + LLM question per hint', () => {
    const hints: MissingFieldHint[] = [
      {
        field_path: 'explicit_task.target_ts_code',
        reason: 'llm_uncertain',
        llm_question_for_user: '请确认目标股票 ts_code (601398.SH ?)',
      },
      {
        field_path: 'explicit_task.user_extra_message',
        reason: 'schema_required_but_empty',
        llm_question_for_user: '是否还有其他要求?',
      },
    ]
    render(<MissingFieldBanner hints={hints} />)
    expect(screen.getByText(/请确认目标股票 ts_code/)).toBeInTheDocument()
    expect(screen.getByText(/是否还有其他要求/)).toBeInTheDocument()
  })

  it('shows reason tag per hint', () => {
    const hints: MissingFieldHint[] = [
      { field_path: 'a.b', reason: 'llm_uncertain', llm_question_for_user: 'q1' },
      { field_path: 'c.d', reason: 'schema_required_but_empty', llm_question_for_user: 'q2' },
    ]
    render(<MissingFieldBanner hints={hints} />)
    expect(screen.getByText(/llm_uncertain/)).toBeInTheDocument()
    expect(screen.getByText(/schema_required_but_empty/)).toBeInTheDocument()
  })
})
