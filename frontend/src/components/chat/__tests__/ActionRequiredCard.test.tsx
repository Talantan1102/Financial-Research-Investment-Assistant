import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test-utils/render'
import { ActionRequiredCard } from '@/components/chat/ActionRequiredCard'

const outcome = {
  code: 'action_required' as const,
  action_type: 'apply_market_permission',
  action_url: '/market-permissions/star/apply',
  action_label: '申请科创板权限',
  resume_hint: '完成申请后回到这里继续下单。',
  intent_summary: '买入中芯国际 100 股',
}

describe('<ActionRequiredCard>', () => {
  it('uses an internal link and does not continue automatically', () => {
    const onContinue = vi.fn()
    renderWithProviders(<ActionRequiredCard outcome={outcome} onContinue={onContinue} />)

    expect(screen.getByRole('link', { name: outcome.action_label })).toHaveAttribute(
      'href', outcome.action_url,
    )
    expect(onContinue).not.toHaveBeenCalled()
  })

  it('asks the chat to create a new explicit turn only after the user chooses continue', async () => {
    const user = userEvent.setup()
    const onContinue = vi.fn()
    renderWithProviders(<ActionRequiredCard outcome={outcome} onContinue={onContinue} />)

    await user.click(screen.getByRole('button', { name: '我已完成，继续' }))
    expect(onContinue).toHaveBeenCalledWith(
      '我已完成外部操作，请重新检查并继续：买入中芯国际 100 股',
    )
  })
})
