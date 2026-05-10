import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, beforeEach } from 'vitest'
import { InlineEditField } from '@/components/escalation/InlineEditField'
import { escalationActions, escalationState } from '@/store/escalation'

describe('<InlineEditField>', () => {
  beforeEach(() => {
    escalationActions.reset()
  })

  it('shows value + edit pencil button by default', () => {
    render(<InlineEditField fieldPath="explicit_task.extracted_intent" llmValue="投资尽调" />)
    expect(screen.getByDisplayValue('投资尽调')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /编辑|edit/i })).toBeInTheDocument()
  })

  it('clicking edit pencil enables input', async () => {
    const user = userEvent.setup()
    render(<InlineEditField fieldPath="explicit_task.extracted_intent" llmValue="投资尽调" />)
    await user.click(screen.getByRole('button', { name: /编辑|edit/i }))
    const input = screen.getByDisplayValue('投资尽调') as HTMLInputElement
    expect(input.readOnly).toBe(false)
  })

  it('on save pushes FieldEdit{modify} into store.user_edits', async () => {
    const user = userEvent.setup()
    render(<InlineEditField fieldPath="explicit_task.extracted_intent" llmValue="投资尽调" />)
    await user.click(screen.getByRole('button', { name: /编辑|edit/i }))
    const input = screen.getByDisplayValue('投资尽调')
    await user.clear(input)
    await user.type(input, '尽调 + 风险评估')
    await user.click(screen.getByRole('button', { name: /保存|save/i }))
    expect(escalationState.user_edits).toEqual([
      {
        field_path: 'explicit_task.extracted_intent',
        llm_value: '投资尽调',
        user_value: '尽调 + 风险评估',
        edit_type: 'modify',
      },
    ])
  })

  it('on save with empty value pushes FieldEdit{delete}', async () => {
    const user = userEvent.setup()
    render(<InlineEditField fieldPath="explicit_task.target_ts_code" llmValue="601398.SH" />)
    await user.click(screen.getByRole('button', { name: /编辑|edit/i }))
    const input = screen.getByDisplayValue('601398.SH')
    await user.clear(input)
    await user.click(screen.getByRole('button', { name: /保存|save/i }))
    expect(escalationState.user_edits[0]?.edit_type).toBe('delete')
  })
})
